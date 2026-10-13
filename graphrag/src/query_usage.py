"""Contabilidade isolada por consulta, incluindo chamadas em asyncio.to_thread."""
from contextlib import contextmanager
from contextvars import ContextVar
import os
import threading
import math

_current = ContextVar("query_usage", default=None)
_depth = ContextVar("llm_call_depth", default=0)


class Usage:
    def __init__(self):
        self.lock = threading.Lock()
        self.calls = []
        self.active = 0

    def snapshot(self):
        with self.lock:
            calls = list(self.calls)
            active = self.active
        complete = bool(calls) and not active and all(c["reported"] for c in calls)
        incoming = sum(c["input_tokens"] for c in calls)
        outgoing = sum(c["output_tokens"] for c in calls)
        cost = None
        # Tarifas são explícitas, sem presumir preços atuais dos provedores.
        try:
            prices = (float(os.environ["RAG_INPUT_COST_PER_MILLION_USD"]), float(os.environ["RAG_OUTPUT_COST_PER_MILLION_USD"]))
            if complete and all(math.isfinite(p) and p >= 0 for p in prices):
                cost = (incoming * prices[0] + outgoing * prices[1]) / 1_000_000
        except (KeyError, ValueError):
            pass
        return {"llm_calls": len(calls), "pending_llm_calls": active, "reported_input_tokens": incoming,
                "reported_output_tokens": outgoing, "token_usage_complete": complete,
                "cost_usd": cost, "cost_method": "configured_blended_rates" if cost is not None else "unavailable"}


@contextmanager
def usage_scope():
    usage = Usage()
    token = _current.set(usage)
    try:
        yield usage
    finally:
        _current.reset(token)


@contextmanager
def tracked_call():
    collector = _current.get()
    outer = _depth.get() == 0
    token = _depth.set(_depth.get() + 1)
    if collector is not None and outer:
        with collector.lock:
            collector.active += 1
    result = []
    try:
        yield result.append
    finally:
        _depth.reset(token)
        if collector is not None and outer:
            response = result[0] if result else None
            usage = getattr(response, "usage", None)
            raw = getattr(response, "raw", None)
            if usage is None and raw is not None:
                usage = raw.get("usage") if isinstance(raw, dict) else getattr(raw, "usage", None)
            if hasattr(usage, "model_dump"):
                usage = usage.model_dump()
            valid = isinstance(usage, dict) and "prompt_tokens" in usage and "completion_tokens" in usage
            try:
                incoming, outgoing = (int(usage["prompt_tokens"]), int(usage["completion_tokens"])) if valid else (0, 0)
            except (TypeError, ValueError):
                incoming, outgoing, valid = 0, 0, False
            with collector.lock:
                collector.active -= 1
                collector.calls.append({"reported": valid, "input_tokens": max(0, incoming), "output_tokens": max(0, outgoing)})
