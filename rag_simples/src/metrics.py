"""Métricas locais de baixa cardinalidade, exportadas no formato Prometheus."""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware

from runtime import estimate_tokens

_lock = threading.Lock()
_http: dict[tuple[str, str], dict] = defaultdict(
    lambda: {"count": 0, "errors": 0, "latency_sum": 0.0, "latency_max": 0.0}
)
_usage: dict[str, dict] = defaultdict(
    lambda: {
        "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0,
        "reported_input_tokens": 0, "reported_output_tokens": 0,
        "reported_cost_usd": 0.0,
    }
)
_OBSERVED_PATHS = {"/query", "/route", "/health"}


def _price(env_name: str) -> float:
    try:
        return max(float(os.getenv(env_name, "0")), 0.0)
    except ValueError:
        return 0.0


def record_http(service: str, path: str, status: int, latency_ms: float) -> None:
    if path not in _OBSERVED_PATHS:
        return
    with _lock:
        item = _http[(service, path)]
        item["count"] += 1
        item["errors"] += int(status >= 400)
        item["latency_sum"] += latency_ms
        item["latency_max"] = max(item["latency_max"], latency_ms)


def record_estimated_usage(service: str, input_text: str, output_text: str) -> dict:
    input_tokens = estimate_tokens(input_text)
    output_tokens = estimate_tokens(output_text)
    cost = (
        input_tokens * _price("RAG_INPUT_COST_PER_MILLION_USD")
        + output_tokens * _price("RAG_OUTPUT_COST_PER_MILLION_USD")
    ) / 1_000_000
    with _lock:
        item = _usage[service]
        item["input_tokens"] += input_tokens
        item["output_tokens"] += output_tokens
        item["estimated_cost_usd"] += cost
    return {
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
        "estimated_cost_usd": cost,
    }


def record_reported_usage(service: str, response) -> None:
    """Registra usage reportado por clientes OpenAI-compatíveis, quando disponível."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    input_tokens = getattr(usage, "prompt_tokens", None)
    if input_tokens is None:
        input_tokens = getattr(usage, "input_tokens", 0)
    output_tokens = getattr(usage, "completion_tokens", None)
    if output_tokens is None:
        output_tokens = getattr(usage, "output_tokens", 0)
    try:
        input_tokens = max(int(input_tokens or 0), 0)
        output_tokens = max(int(output_tokens or 0), 0)
    except (TypeError, ValueError):
        return
    cost = (
        input_tokens * _price("RAG_INPUT_COST_PER_MILLION_USD")
        + output_tokens * _price("RAG_OUTPUT_COST_PER_MILLION_USD")
    ) / 1_000_000
    with _lock:
        item = _usage[service]
        item["reported_input_tokens"] += input_tokens
        item["reported_output_tokens"] += output_tokens
        item["reported_cost_usd"] += cost


def snapshot() -> dict:
    with _lock:
        return {
            "http": {key: dict(value) for key, value in _http.items()},
            "usage": {key: dict(value) for key, value in _usage.items()},
        }


def render_prometheus() -> str:
    lines = [
        "# HELP rag_http_requests_total Requisições HTTP observadas.",
        "# TYPE rag_http_requests_total counter",
    ]
    with _lock:
        for (service, path), item in sorted(_http.items()):
            labels = f'service="{service}",path="{path}"'
            lines.append(f"rag_http_requests_total{{{labels}}} {item['count']}")
            lines.append(f"rag_http_errors_total{{{labels}}} {item['errors']}")
            lines.append(
                f"rag_http_request_latency_ms_sum{{{labels}}} {item['latency_sum']:.3f}"
            )
            lines.append(
                f"rag_http_request_latency_ms_max{{{labels}}} {item['latency_max']:.3f}"
            )
        for service, item in sorted(_usage.items()):
            label = f'service="{service}"'
            lines.append(
                f"rag_estimated_input_tokens_total{{{label}}} {item['input_tokens']}"
            )
            lines.append(
                f"rag_estimated_output_tokens_total{{{label}}} {item['output_tokens']}"
            )
            lines.append(
                f"rag_estimated_cost_usd_total{{{label}}} {item['estimated_cost_usd']:.9f}"
            )
            lines.append(
                f"rag_reported_input_tokens_total{{{label}}} {item['reported_input_tokens']}"
            )
            lines.append(
                f"rag_reported_output_tokens_total{{{label}}} {item['reported_output_tokens']}"
            )
            lines.append(
                f"rag_reported_cost_usd_total{{{label}}} {item['reported_cost_usd']:.9f}"
            )
    return "\n".join(lines) + "\n"


class MetricsMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, service_name: str):
        super().__init__(app)
        self.service_name = service_name

    async def dispatch(self, request, call_next):
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            latency_ms = (time.perf_counter() - started) * 1000
            record_http(self.service_name, request.url.path, status, latency_ms)
