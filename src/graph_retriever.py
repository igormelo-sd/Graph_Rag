"""
Graph Retriever — recupera nós de texto via travessia do grafo de conhecimento.

Usa LLMSynonymRetriever: dado uma query, o LLM gera sinônimos e termos
relacionados, que são usados para encontrar entidades no grafo e retornar
os chunks de texto originais que as mencionam.

Deduplicação: remove nós já presentes no contexto de outros retrievers para
evitar repetição de conteúdo na síntese.
"""
import os

from llama_index.core.indices.property_graph import LLMSynonymRetriever
from logger import get_logger

log = get_logger(__name__)


class GraphRetriever:
    """
    Wrapper sobre LLMSynonymRetriever para integração com AnalysisEngine.

    O retriever expande a query com sinônimos de entidades econômicas
    (indicadores, setores, fontes) e busca nós conectados no grafo.
    """

    def __init__(self, graph_index, llm):
        self._retriever = LLMSynonymRetriever(
            graph_store=graph_index.property_graph_store,
            include_text=True,
            max_keywords=10,
            path_depth=2,
            llm=llm,
        )

    def retrieve(self, question: str, exclude_ids: set | None = None) -> list:
        """
        Retorna nós de texto recuperados via grafo.

        Parâmetros
        ----------
        question : str
            Query (reescrita pelo interpreter).
        exclude_ids : set | None
            IDs de nós já presentes em outros retrievers — serão filtrados
            para evitar duplicação no contexto.

        Retorna
        -------
        list[NodeWithScore] com conteúdo não-vazio e não-duplicado.
        """
        try:
            nodes = self._retriever.retrieve(question)
        except Exception as exc:
            log.warning("[Graph] Falha no retrieval: %s", exc)
            return []

        seen = exclude_ids or set()
        result = []
        for n in nodes:
            nid = getattr(n.node, "node_id", None) or id(n)
            if nid not in seen and n.get_content().strip():
                result.append(n)
                seen.add(nid)

        log.info("[Graph] %d nós recuperados pelo grafo", len(result))
        return result

    def retrieve_neighbors(self, nodes: list, db_path: str | None = None, limit_per_node: int = 1) -> list:
        """Costura contexto dividido: traz NEXT_CHUNK/SAME_PAGE vizinhos (determinístico, sem LLM)."""
        if not nodes:
            return []
        try:
            from indexing import load_nodes_cache
            from index_manifest import resolve_db_dir

            if db_path is None:
                try:
                    db_path = resolve_db_dir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                except Exception:
                    db_path = "./chroma_db"
            all_nodes = load_nodes_cache(db_path)
            if not all_nodes:
                return []
            # índice por (source_file, page, chunk_id)
            idx: dict[tuple, object] = {}
            for n in all_nodes:
                md = getattr(n, "metadata", {}) or {}
                key = (str(md.get("source_file") or ""), str(md.get("page") or ""), str(md.get("chunk_id") or ""))
                idx[key] = n
            neighbors = []
            seen = set()
            for n in nodes:
                md = getattr(n, "metadata", {}) or {}
                src, page, cid = str(md.get("source_file") or ""), str(md.get("page") or ""), md.get("chunk_id")
                if cid is None:
                    continue
                try:
                    cid_int = int(cid)
                except Exception:
                    continue
                for delta in (-1, 1):
                    key = (src, page, str(cid_int + delta))
                    nb = idx.get(key)
                    if nb is not None:
                        nid = getattr(getattr(nb, "node", nb), "node_id", None) or id(nb)
                        if nid not in seen:
                            # limita 1 vizinho por direção
                            neighbors.append(nb)
                            seen.add(nid)
                            if len(neighbors) >= len(nodes) * limit_per_node:
                                break
                if len(neighbors) >= len(nodes) * limit_per_node:
                    break
            if neighbors:
                log.info("[Graph] Costura: %d vizinhos NEXT_CHUNK/SAME_PAGE", len(neighbors))
            return neighbors
        except Exception as exc:
            log.warning("[Graph] Falha ao costurar vizinhos: %s", exc)
            return []
