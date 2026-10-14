"""Normalização mínima de proveniência para todas as APIs RAG."""
from __future__ import annotations

import math


def source_file(node) -> str:
    metadata = getattr(node, "metadata", {}) or {}
    value = (
        metadata.get("source_files")
        or metadata.get("source_file")
        or metadata.get("file_name")
        or "?"
    )
    return str(value)


def source_page(node) -> str | int | None:
    metadata = getattr(node, "metadata", {}) or {}
    value = metadata.get("page")
    return value if isinstance(value, (str, int)) else None


def relevance_score(node) -> float:
    """Normaliza similaridade 0–1 e notas de reranker 0–10 para 0–1."""
    raw = getattr(node, "score", None)
    if raw is None:
        return 0.0
    try:
        score = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(score):
        return 0.0
    if score > 1.0:
        score /= 10.0
    return round(min(max(score, 0.0), 1.0), 2)


def source_label(node) -> str:
    page = source_page(node)
    suffix = f", p./aba {page}" if page is not None else ""
    return f"Fonte: {source_file(node)}{suffix}"


def format_source_context(node) -> str:
    """Anexa proveniência ao trecho efetivamente enviado ao LLM."""
    return f"[{source_label(node)}]\n{node.get_content()}"


def source_labels(nodes: list) -> str:
    labels = list(dict.fromkeys(source_label(node) for node in nodes))
    return "\n".join(f"[{label}]" for label in labels)


def _item_source_and_page(item) -> tuple[str, str]:
    metadata = getattr(item, "metadata", {}) or {}
    src = (
        metadata.get("source_files")
        or metadata.get("source_file")
        or metadata.get("file_name")
        or ""
    )
    page = metadata.get("page")
    page_str = "" if page is None else str(page)
    return str(src), page_str


def assign_page_metadata(nodes, documents=()):
    """Numera nós dentro de cada fonte/página e propaga seções literais."""
    from collections import Counter

    totals = Counter(_item_source_and_page(node) for node in nodes)
    counters = Counter()
    sections = {
        _item_source_and_page(doc): (getattr(doc, "metadata", {}) or {})["section"]
        for doc in documents
        if (getattr(doc, "metadata", {}) or {}).get("section")
    }
    for node in nodes:
        identity = _item_source_and_page(node)
        counters[identity] += 1
        meta = getattr(node, "metadata", None)
        if meta is None:
            node.metadata = meta = {}
        meta["chunk_id"] = counters[identity]
        meta["total_chunks_page"] = totals[identity]
        if not meta.get("section") and identity in sections:
            meta["section"] = sections[identity]


def sanitize_text(text: str) -> str:
    """Remove caracteres de controle inválidos que podem quebrar o JSON da API."""
    if not text:
        return ""
    import re
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)


def sanitize_nodes(nodes: list) -> list:
    """Sanitiza nós antes do reranker sem mutar o nó original no cache compartilhado."""
    from copy import copy
    from llama_index.core.schema import NodeWithScore

    sanitized = []
    for n in nodes:
        node_obj = getattr(n, "node", n)
        text = getattr(node_obj, "text", "")
        clean = sanitize_text(text)
        if clean == text:
            sanitized.append(n)
        else:
            new_node = copy(node_obj)
            new_node.text = clean
            if hasattr(n, "score"):
                sanitized.append(NodeWithScore(node=new_node, score=n.score))
            else:
                sanitized.append(new_node)
    return sanitized
