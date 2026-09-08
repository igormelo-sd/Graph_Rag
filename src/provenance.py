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
