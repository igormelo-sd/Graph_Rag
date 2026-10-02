"""
Startup — inicialização compartilhada do sistema RAG.

Usado tanto pela API (FastAPI lifespan) quanto pelo CLI interativo.
Centraliza: detecção de mudanças, indexação, criação de LLMs e retrievers.
"""
import os
from pathlib import Path

from llama_index.core import Settings
from llama_index.core.postprocessor import LLMRerank

from llm import make_llm, require_api_key
from logger import get_logger, setup_logging
from index_manifest import (
    resolve_data_dir,
    resolve_db_dir,
)
from index_sync import sync_standard_index
from indexing import load_nodes_cache
from scripts.index_artifact import (
    DEFAULT_RELEASE_ASSET,
    DEFAULT_RELEASE_REPO,
    DEFAULT_RELEASE_TAG,
    ensure_release_index,
)
from text_retriever import (
    build_hybrid_retriever,
    llm_reranking_enabled,
    rerank_top_n,
    ScoreReranker,
    TextRetriever,
)
from images_retriever import ImagesRetriever
from tables_retriever import TablesRetriever
from timeseries_retriever import TimeSeriesRetriever
from graph_indexing import build_or_load_graph
from graph_retriever import GraphRetriever
from analysis_engine import AnalysisEngine
from domain_skills import DomainSkillRegistry
from load_control import LimitedReranker

log = get_logger(__name__)


def graph_enabled_by_env() -> bool:
    """True se RAG_USE_GRAPH estiver ligada (1/true/yes/on)."""
    return os.getenv("RAG_USE_GRAPH", "").strip().lower() in {"1", "true", "yes", "on"}


def _env_enabled(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def ensure_principal_index(db_path: str) -> None:
    """Baixa índice portátil quando banco local ainda não existe.

    Não força mais RAG_INDEX_READ_ONLY: download e modo de operação são
    decisões independentes (RAG_INDEX_AUTO_DOWNLOAD vs RAG_INDEX_READ_ONLY).
    """
    if not _env_enabled("RAG_INDEX_AUTO_DOWNLOAD", "0"):
        return
    repo = os.getenv("RAG_INDEX_REPO", DEFAULT_RELEASE_REPO)
    tag = os.getenv("RAG_INDEX_TAG", DEFAULT_RELEASE_TAG)
    asset = os.getenv("RAG_INDEX_ASSET", DEFAULT_RELEASE_ASSET)
    token = os.getenv("GITHUB_TOKEN") or None
    try:
        timeout = float(os.getenv("RAG_INDEX_DOWNLOAD_TIMEOUT", "600"))
    except ValueError as exc:
        raise RuntimeError("RAG_INDEX_DOWNLOAD_TIMEOUT deve ser numérico.") from exc

    log.info("[0] Verificando índice vetorial portátil")
    count, downloaded = ensure_release_index(
        target=Path(db_path),
        repo=repo,
        tag=tag,
        asset=asset,
        token=token,
        timeout=timeout,
    )
    if downloaded:
        log.info("[0] Índice baixado e validado (%d vetores)", count)
    else:
        log.info("[0] Índice local válido (%d vetores); download dispensado", count)


# ── Detecção de mudanças ──────────────────────────────────────────────────────

# ── Inicialização principal ───────────────────────────────────────────────────

def initialize(base_dir: str, data_dir: str | None = None, use_graph: bool = False) -> tuple[AnalysisEngine, object]:
    """
    Inicializa o sistema completo e retorna (engine, interp_llm).

    Parâmetros
    ----------
    base_dir : str
        Diretório raiz do RAG (onde fica /chroma_db).
    data_dir : str | None
        Diretório dos documentos. Se None, resolve a base local compartilhada
        ou base_dir/data (container).
        Útil quando evaluate.py roda de um diretório diferente do RAG.
    use_graph : bool
        Se True, constrói/carrega o grafo de conhecimento e habilita a
        4ª fonte "graph" no AnalysisEngine.

    Retorna
    -------
    engine : AnalysisEngine
        Engine pronta para receber queries.
    interp_llm : OpenAI
        LLM leve usado pelo Query Interpreter.
    """
    require_api_key()

    setup_logging()
    data_dir = resolve_data_dir(base_dir, data_dir)
    db_path = resolve_db_dir(base_dir)

    log.info("Inicializando RAG Estatistico SP")

    # 0. Bootstrap portátil: baixa uma vez, valida e impede reindexação implícita.
    ensure_principal_index(db_path)

    # 1–3. Detecção, ingestão seletiva e sincronização vetorial/BM25
    index, changed = sync_standard_index(data_dir, db_path, log)

    # 4. LLMs
    log.info("[3] Carregando modelos de linguagem")
    llm = make_llm(temperature=0.0, timeout=60.0)
    Settings.llm = llm
    interp_llm  = make_llm(interp=True, temperature=0.0, timeout=30.0)

    # 5. Retriever híbrido compartilhado + reranker
    log.info("[4] Inicializando retrievers")
    bm25_nodes = load_nodes_cache(db_path)
    text_retriever = build_hybrid_retriever(
        index, bm25_nodes, node_type="text", llm=interp_llm
    )
    table_retriever = build_hybrid_retriever(
        index, bm25_nodes, node_type="table", llm=interp_llm
    )
    image_retriever = build_hybrid_retriever(
        index, bm25_nodes, node_type="image", llm=interp_llm
    )
    # BGE reranker local (cross-encoder) tem prioridade quando habilitado — mais rápido que LLM
    # Default 1: local e superior para PT-BR (bge-reranker-v2-m3) — P0
    if os.getenv("RAG_BGE_RERANK", "1").strip().lower() in {"1", "true", "yes", "on"}:
        try:
            from llama_index.core.postprocessor import SentenceTransformerRerank

            reranker = SentenceTransformerRerank(
                model="BAAI/bge-reranker-v2-m3", top_n=rerank_top_n()
            )
            log.info("Reranking por BGE cross-encoder (bge-reranker-v2-m3) ativado")
        except Exception as exc:
            log.warning("BGE reranker falhou (%s) — caindo para LLM rerank", exc)
            if llm_reranking_enabled():
                reranker = LLMRerank(top_n=rerank_top_n(), choice_batch_size=30, llm=interp_llm)
            else:
                reranker = ScoreReranker(top_n=rerank_top_n())
    elif llm_reranking_enabled():
        # Em provedores com janela/latência adequadas, o LLM refina os
        # candidatos híbridos em lotes controlados.
        reranker = LLMRerank(top_n=rerank_top_n(), choice_batch_size=30, llm=interp_llm)
    else:
        # Ollama local: preserva o score híbrido e evita prompts maiores que a
        # janela ativa do modelo, além de eliminar uma chamada lenta por busca.
        reranker = ScoreReranker(top_n=rerank_top_n())
        log.info("Reranking por LLM desativado; usando ranking hibrido Vector+BM25")

    # 6. Quatro retrievers especializados
    reranker = LimitedReranker(reranker)
    text_ret   = TextRetriever(text_retriever, reranker)
    tables_ret = TablesRetriever(table_retriever, reranker, llm)
    ts_ret     = TimeSeriesRetriever(table_retriever, reranker, llm)
    images_ret = ImagesRetriever(image_retriever, reranker)

    # 7. Skills de domínio (opcionais — descobertas em .agents/skills)
    domain_skills = DomainSkillRegistry(base_dir)
    if domain_skills.is_loaded():
        log.info("[5] Skills de domínio carregadas: %s", domain_skills.available_domains())
    else:
        log.info("[5] Skills de domínio não encontradas (opcional)")

    # 8. Grafo de conhecimento — sempre ativo (estrutural determinístico custo zero)
    # P0: RAG_GRAPH_STRUCT=1 por padrão; RAG_GRAPH_EMBED=1 ativa 2º embedding; --graph força LLM extraction
    graph_ret = None
    _graph_embed = os.getenv("RAG_GRAPH_EMBED", "0").strip().lower() in {"1", "true", "yes", "on"}
    _graph_struct = os.getenv("RAG_GRAPH_STRUCT", "1").strip().lower() in {"1", "true", "yes", "on"}
    use_graph = use_graph or graph_enabled_by_env()
    if use_graph or _graph_embed or _graph_struct:
        log.info("[6] Inicializando grafo de conhecimento%s", " (2º embedding)" if _graph_embed else "")
        all_nodes = load_nodes_cache(db_path)
        force_rebuild = bool(changed)
        graph_index = build_or_load_graph(
            all_nodes, base_dir, llm, force_rebuild=force_rebuild,
            use_llm=use_graph,
        )
        graph_ret = GraphRetriever(graph_index, interp_llm)
        log.info("[6] Grafo pronto")
    else:
        log.info("[6] Grafo desativado (use --graph no CLI ou RAG_USE_GRAPH=1)")

    # 9. Analysis Engine
    engine = AnalysisEngine(
        text_ret, tables_ret, ts_ret, llm,
        domain_skills=domain_skills,
        graph_retriever=graph_ret,
        images_retriever=images_ret,
    )

    log.info("Sistema pronto")
    return engine, interp_llm
