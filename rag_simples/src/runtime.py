"""Compatibilidade: implementação comum em rag_app.runtime."""
from rag_app.runtime import (
    bounded_int,
    bounded_float,
    request_timeout_seconds,
    context_token_budget,
    estimate_tokens,
    limit_context,
    limit_chat_messages,
)

__all__ = ['bounded_int', 'bounded_float', 'request_timeout_seconds', 'context_token_budget', 'estimate_tokens', 'limit_context', 'limit_chat_messages']
