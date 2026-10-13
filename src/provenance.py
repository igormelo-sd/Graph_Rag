"""Compatibilidade: implementação comum em rag_app.provenance."""
from rag_app.provenance import (
    source_file,
    source_page,
    relevance_score,
    source_label,
    format_source_context,
    source_labels,
    assign_page_metadata,
)

__all__ = [
    'source_file', 'source_page', 'relevance_score',
    'source_label', 'format_source_context', 'source_labels',
    'assign_page_metadata',
]
