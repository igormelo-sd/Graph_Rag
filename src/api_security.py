"""
api_security.py — proteções HTTP compartilhadas, sem dependências extras.

Ambos são **opt-in** via variáveis de ambiente, preservando compatibilidade:

    RAG_API_KEY      Se definido, exige o header 'x-api-key' igual em cada
                     requisição a /query. Se ausente/vazio, a autenticação fica
                     desligada (comportamento atual).
    RAG_BACKEND_API_KEY
                     Chave opcional para chamadas internas do orquestrador.
    RAG_CORS_ORIGINS Lista explícita de origens permitidas. O padrão aceita
                     somente as interfaces locais do projeto.
    RAG_RATE_LIMIT   Máximo de requisições por IP dentro da janela (default 30).
                     0 ou negativo desliga o rate limiting.
    RAG_RATE_WINDOW  Tamanho da janela deslizante em segundos (default 60).

As funções de autenticação e limite são dependências do FastAPI — plugue-as com
``Depends(...)``. O rate limiter usa uma janela deslizante em memória por IP;
para múltiplas réplicas do processo, troque por um backend compartilhado (Redis).
"""
from __future__ import annotations

import os
import hmac
import threading
import time
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

_hits: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()

_DEFAULT_CORS_ORIGINS = (
    "http://localhost:8000,http://127.0.0.1:8000,"
    "http://localhost:5173,http://127.0.0.1:5173,"
    "http://localhost:8501,http://127.0.0.1:8501"
)

_DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "font-src 'self' https://cdn.jsdelivr.net; "
    "connect-src 'self' http://localhost:* http://127.0.0.1:*; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)


def cors_origins() -> list[str]:
    """Origens CORS explícitas; ``*`` continua disponível somente por opt-in."""
    raw = os.getenv("RAG_CORS_ORIGINS", _DEFAULT_CORS_ORIGINS)
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return origins or _DEFAULT_CORS_ORIGINS.split(",")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adiciona headers defensivos às APIs e ao frontend estático montado."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")

        csp = os.getenv("RAG_CONTENT_SECURITY_POLICY", _DEFAULT_CSP).strip()
        if csp:
            response.headers.setdefault("Content-Security-Policy", csp)
        if os.getenv("RAG_ENABLE_HSTS", "0").lower() in {"1", "true", "yes", "on"}:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


def _rate_limit_config() -> tuple[int, float]:
    try:
        limit = int(os.getenv("RAG_RATE_LIMIT", "30"))
    except ValueError:
        limit = 30
    try:
        window = float(os.getenv("RAG_RATE_WINDOW", "60"))
    except ValueError:
        window = 60.0
    return limit, window


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Aceita a chave pública ou interna quando ao menos uma estiver configurada."""
    expected = [
        key for key in (os.getenv("RAG_API_KEY"), os.getenv("RAG_BACKEND_API_KEY"))
        if key
    ]
    if not expected:
        return
    provided = x_api_key or ""
    if not any(hmac.compare_digest(provided, key) for key in expected):
        raise HTTPException(status_code=401, detail="API key inválida ou ausente.")


def enforce_rate_limit(request: Request) -> None:
    """Janela deslizante por IP; 429 ao exceder RAG_RATE_LIMIT requisições."""
    limit, window = _rate_limit_config()
    if limit <= 0:
        return
    client = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _lock:
        dq = _hits[client]
        while dq and now - dq[0] > window:
            dq.popleft()
        if len(dq) >= limit:
            raise HTTPException(
                status_code=429,
                detail="Limite de requisições excedido. Tente novamente em instantes.",
            )
        dq.append(now)
