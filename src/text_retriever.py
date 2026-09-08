"""
Text Retriever — retrieval híbrido (Vector + BM25) para chunks de texto narrativo.

Expõe também build_hybrid_retriever(), usado pelos outros retrievers.
"""
import os
import re
from collections import defaultdict

from llama_index.core.retrievers import VectorIndexRetriever, QueryFusionRetriever
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters
from llama_index.retrievers.bm25 import BM25Retriever
import Stemmer

from logger import get_logger
from llm import provider_name
from runtime import bounded_int

log = get_logger(__name__)
_FALLBACK_TOP_N = 5

_QUERY_GEN_PROMPT = """\
Gere {num_queries} versões alternativas da consulta abaixo para ampliar a busca em
documentos econômicos em português. Preserve setor, local, período e indicador.
Retorne somente uma consulta por linha, sem numeração ou explicações.

Consulta: {query}
"""


def retrieval_top_k() -> int:
    return bounded_int("RAG_RETRIEVAL_TOP_K", 80, 20, 200)


def query_fusion_queries() -> int:
    return bounded_int("RAG_QUERY_FUSION_QUERIES", 2, 1, 4)


def rerank_candidate_limit() -> int:
    return bounded_int("RAG_RERANK_CANDIDATE_LIMIT", 40, 10, 100)


def rerank_top_n() -> int:
    return bounded_int("RAG_RERANK_TOP_N", 24, 5, 50)


def text_top_n() -> int:
    return bounded_int("RAG_TEXT_TOP_N", 20, 5, 40)


def structured_top_n() -> int:
    return bounded_int("RAG_STRUCTURED_TOP_N", 10, 3, 20)


def max_chunks_per_document() -> int:
    return bounded_int("RAG_MAX_CHUNKS_PER_DOCUMENT", 3, 1, 10)


def llm_reranking_enabled() -> bool:
    """Define se os candidatos devem ser reranqueados por um LLM.

    No Ollama local, o lote de candidatos excede facilmente a janela ativa do
    modelo e o processamento em CPU adiciona dezenas de segundos à consulta.
    O ranking híbrido Vector+BM25 é usado por padrão nesse caso.
    """
    raw = os.getenv("RAG_LLM_RERANK")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return provider_name() != "ollama"


class ScoreReranker:
    """Reranker determinístico que preserva a ordem do retriever híbrido."""

    def __init__(self, top_n: int = _FALLBACK_TOP_N):
        self.top_n = top_n

    def postprocess_nodes(self, nodes, query_str: str | None = None):
        del query_str
        return list(nodes[:self.top_n])


def _sanitize(text: str) -> str:
    """Remove caracteres de controle inválidos que podem quebrar o JSON da API."""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)


def _nodes_by_type(nodes, node_type: str | None) -> list:
    if node_type is None:
        return list(nodes or [])
    return [
        node for node in (nodes or [])
        if (getattr(node, "metadata", {}) or {}).get("type") == node_type
    ]


def _raptor_level_of(node) -> int:
    try:
        return max(int((getattr(node, "metadata", {}) or {}).get("raptor_level", 0)), 0)
    except (TypeError, ValueError):
        return 0


def _diversify_by_document(nodes, limit: int | None = None) -> list:
    """Prioriza variedade documental sem descartar resultados relevantes.

    Reserva até 25% do limite para resumos RAPTOR (raptor_level>0) quando existirem,
    para que as folhas não expulsem o contexto amplo. Sem resumos, comportamento inalterado.
    """
    limit = limit or text_top_n()
    per_document = max_chunks_per_document()
    selected, overflow = [], []
    counts: dict[str, int] = defaultdict(int)

    for node in nodes:
        metadata = getattr(node, "metadata", {}) or {}
        source = str(
            metadata.get("source_files")
            or metadata.get("source_file")
            or metadata.get("file_name")
            or "?"
        ).lower()
        if counts[source] < per_document:
            selected.append(node)
            counts[source] += 1
        else:
            overflow.append(node)

    ranked = (selected + overflow)[:limit]
    summaries = [n for n in ranked if _raptor_level_of(n) > 0]
    if not summaries:
        # tenta resgatar resumos bem ranqueados que ficaram fora do corte
        pool_summaries = [n for n in (selected + overflow) if _raptor_level_of(n) > 0]
        if not pool_summaries:
            return ranked
        quota = max(1, limit // 4)
        keep = [n for n in ranked if _raptor_level_of(n) == 0][: limit - quota]
        return (pool_summaries[:quota] + keep)[:limit]
    return ranked


def build_hybrid_retriever(index, bm25_nodes, *, node_type: str | None = None, llm=None):
    """
    Cria retriever híbrido (Vector + BM25 com fusão Reciprocal Rank).
    Se não houver nós BM25, retorna apenas o retriever vetorial.
    """
    top_k = retrieval_top_k()
    filters = None
    if node_type is not None:
        filters = MetadataFilters(filters=[MetadataFilter(key="type", value=node_type)])
    vector_retriever = VectorIndexRetriever(
        index=index,
        similarity_top_k=top_k,
        filters=filters,
    )

    typed_bm25_nodes = _nodes_by_type(bm25_nodes, node_type)
    if typed_bm25_nodes:
        bm25_retriever = BM25Retriever.from_defaults(
            nodes=typed_bm25_nodes,
            similarity_top_k=top_k,
            language="portuguese",
            stemmer=Stemmer.Stemmer("portuguese"),
        )
        return QueryFusionRetriever(
            retrievers=[vector_retriever, bm25_retriever],
            llm=llm,
            query_gen_prompt=_QUERY_GEN_PROMPT,
            similarity_top_k=top_k,
            num_queries=query_fusion_queries(),
            mode="reciprocal_rerank",
            use_async=False,
        )

    return vector_retriever


class TextRetriever:
    """
    Recupera chunks de texto narrativo relevantes para a query.

    Fluxo: retrieve (top-K configurável) → filtra texto → rerank → diversidade.
    Fallback: se o reranker falhar ou retornar vazio, preserva o ranking híbrido.
    """

    def __init__(self, retriever, reranker):
        self._retriever = retriever
        self._reranker = reranker

    def retrieve(self, question: str) -> list:
        """Retorna nodes de texto reranqueados. Lista vazia se sem resultados."""
        nodes = self._retriever.retrieve(question)

        # Filtra apenas chunks narrativos (não tabelas)
        text_nodes = [n for n in nodes if n.metadata.get("type") != "table"]
        if not text_nodes:
            return []

        # Sanitiza conteúdo antes do reranker (evita erro 400 na API)
        for n in text_nodes:
            n.node.text = _sanitize(n.node.text)

        try:
            reranked = self._reranker.postprocess_nodes(
                text_nodes[:rerank_candidate_limit()],
                query_str=question,
            )
        except Exception as exc:
            log.warning(
                "Reranker falhou (%s: %s) — usando fallback por score",
                type(exc).__name__,
                exc,
                extra={"fallback": True},
            )
            reranked = []

        # Fallback: reranker vazio → top-N por score de recuperação
        if not reranked:
            log.warning(
                "Reranker retornou vazio — usando fallback top-%d", text_top_n(),
                extra={"fallback": True},
            )
            return _diversify_by_document(text_nodes, text_top_n())

        return _diversify_by_document(reranked, text_top_n())
