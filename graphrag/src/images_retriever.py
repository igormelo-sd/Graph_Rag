"""
Images Retriever — recupera descrições visuais de gráficos e figuras extraídas via visão local.
"""
from __future__ import annotations

import os
from runtime import bounded_int
from logger import get_logger

log = get_logger(__name__)


def image_top_n() -> int:
    return bounded_int("RAG_IMAGE_TOP_N", 4, 1, 10)


class ImagesRetriever:
    """Recupera nós de imagem/gráfico relevantes para a query."""

    def __init__(self, retriever, reranker):
        self._retriever = retriever
        self._reranker = reranker

    def retrieve(self, question: str) -> list:
        if os.getenv("RAG_VISION", "0").strip().lower() not in {"1", "true", "yes", "on"}:
            return []
        try:
            nodes = self._retriever.retrieve(question)
            image_nodes = [n for n in nodes if n.metadata.get("type") == "image"]
            if not image_nodes:
                return []
            try:
                reranked = self._reranker.postprocess_nodes(image_nodes, query_str=question)
            except Exception:
                reranked = image_nodes
            limit = image_top_n()
            return list(reranked[:limit])
        except Exception as exc:
            log.warning("ImagesRetriever falhou: %s", exc)
            return []
