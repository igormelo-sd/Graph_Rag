"""Limites locais por processo para requisições, LLM e reranking."""
import asyncio
from contextlib import asynccontextmanager, contextmanager
from functools import lru_cache
import threading
import weakref
import os

from runtime import bounded_int, bounded_float


class CapacityExceeded(RuntimeError):
    pass


@lru_cache(maxsize=2)
def _semaphore(kind):
    defaults = {"LLM": 1 if os.getenv("RAG_LLM_PROVIDER", "").lower() == "ollama" else 4, "RERANK": 1}
    return threading.BoundedSemaphore(bounded_int(f"RAG_{kind}_CONCURRENCY", defaults[kind], 1, 16))


_local = threading.local()


@contextmanager
def resource_slot(kind):
    # Chamadas complete -> chat da mesma thread compartilham a vaga.
    held = getattr(_local, "held", set())
    if kind in held:
        yield
        return
    semaphore = _semaphore(kind)
    if not semaphore.acquire(timeout=bounded_float("RAG_RESOURCE_WAIT", 10, 0.1, 60)):
        raise CapacityExceeded(f"Capacidade de {kind} esgotada")
    _local.held = held | {kind}
    try:
        yield
    finally:
        _local.held = held
        semaphore.release()


@asynccontextmanager
async def async_resource_slot(kind):
    semaphore = _semaphore(kind)
    deadline = asyncio.get_running_loop().time() + bounded_float("RAG_RESOURCE_WAIT", 10, 0.1, 60)
    while not semaphore.acquire(blocking=False):
        if asyncio.get_running_loop().time() >= deadline:
            raise CapacityExceeded(f"Capacidade de {kind} esgotada")
        await asyncio.sleep(0.05)
    try:
        yield
    finally:
        semaphore.release()


_queues = weakref.WeakKeyDictionary()


@asynccontextmanager
async def request_slot():
    loop = asyncio.get_running_loop()
    state = _queues.get(loop)
    if state is None:
        state = {"semaphore": asyncio.Semaphore(bounded_int("RAG_QUERY_CONCURRENCY", 2, 1, 32)), "admitted": 0}
        _queues[loop] = state
    capacity = bounded_int("RAG_QUERY_CONCURRENCY", 2, 1, 32) + bounded_int("RAG_QUERY_QUEUE", 4, 0, 64)
    if state["admitted"] >= capacity:
        raise CapacityExceeded("Fila de consultas cheia")
    state["admitted"] += 1
    acquired = False
    try:
        try:
            await asyncio.wait_for(state["semaphore"].acquire(), bounded_float("RAG_QUEUE_WAIT", 5, 0.1, 60))
            acquired = True
        except asyncio.TimeoutError as exc:
            raise CapacityExceeded("Tempo de espera na fila excedido") from exc
        yield
    finally:
        if acquired:
            state["semaphore"].release()
        state["admitted"] -= 1


class LimitedReranker:
    def __init__(self, reranker):
        self._reranker = reranker

    def postprocess_nodes(self, *args, **kwargs):
        with resource_slot("RERANK"):
            return self._reranker.postprocess_nodes(*args, **kwargs)
