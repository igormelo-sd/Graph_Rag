"""Limites operacionais compartilhados pelas engines RAG."""
from __future__ import annotations

import os
from copy import copy


def bounded_int(env_name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(env_name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


def bounded_float(env_name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(env_name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


def request_timeout_seconds() -> float:
    return bounded_float("RAG_REQUEST_TIMEOUT", 180.0, 5.0, 600.0)


def context_token_budget() -> int:
    return bounded_int("RAG_MAX_CONTEXT_TOKENS", 12_000, 1_000, 100_000)


def estimate_tokens(text: str) -> int:
    """Estimativa conservadora e sem dependência de tokenizer (≈ 4 chars/token)."""
    return (len(text) + 3) // 4


def limit_context(text: str, max_tokens: int | None = None) -> str:
    """Trunca contexto ao orçamento configurado e sinaliza explicitamente o corte."""
    budget = max_tokens or context_token_budget()
    max_chars = budget * 4
    if len(text) <= max_chars:
        return text
    marker = "\n\n[Contexto truncado pelo orçamento de tokens]"
    return text[: max(0, max_chars - len(marker))].rstrip() + marker


def limit_chat_messages(messages: list[dict], max_tokens: int | None = None) -> list[dict]:
    """Copia mensagens e divide o orçamento restante entre resultados de tools."""
    budget_chars = (max_tokens or context_token_budget()) * 4
    copied = [copy(message) for message in messages]
    tool_messages = [m for m in copied if m.get("role") == "tool"]
    fixed_chars = sum(
        len(str(m.get("content") or ""))
        for m in copied
        if m.get("role") != "tool"
    )
    available = max(budget_chars - fixed_chars, 0)
    per_tool = available // max(len(tool_messages), 1)
    for message in tool_messages:
        message["content"] = limit_context(str(message.get("content") or ""), max(per_tool // 4, 1))
    return copied
