"""
Testes de api_security: autenticação por API key e rate limiting.

Exercita as dependências como funções puras e valida os headers no middleware.

Rode a partir de rag_principal/:
    cd rag_principal && python -m pytest tests/test_api_security.py -q
"""
from types import SimpleNamespace
import asyncio

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

import api_security as sec


def _fake_request(host: str = "1.2.3.4"):
    return SimpleNamespace(client=SimpleNamespace(host=host))


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    sec._hits.clear()
    for var in (
        "RAG_API_KEY", "RAG_BACKEND_API_KEY", "RAG_RATE_LIMIT", "RAG_RATE_WINDOW",
        "RAG_CORS_ORIGINS", "RAG_CONTENT_SECURITY_POLICY", "RAG_ENABLE_HSTS",
    ):
        monkeypatch.delenv(var, raising=False)
    yield
    sec._hits.clear()


# ── API key ───────────────────────────────────────────────────────────────────

def test_sem_api_key_configurada_e_noop():
    # Não deve levantar quando RAG_API_KEY não está definido.
    assert sec.require_api_key(None) is None


def test_api_key_ausente_ou_errada_401(monkeypatch):
    monkeypatch.setenv("RAG_API_KEY", "segredo")
    with pytest.raises(HTTPException) as e1:
        sec.require_api_key(None)
    assert e1.value.status_code == 401
    with pytest.raises(HTTPException):
        sec.require_api_key("errado")


def test_api_key_correta_passa(monkeypatch):
    monkeypatch.setenv("RAG_API_KEY", "segredo")
    assert sec.require_api_key("segredo") is None


def test_api_key_interna_passa(monkeypatch):
    monkeypatch.setenv("RAG_BACKEND_API_KEY", "interna")
    assert sec.require_api_key("interna") is None


def test_comparacao_rejeita_prefixo(monkeypatch):
    monkeypatch.setenv("RAG_API_KEY", "segredo-completo")
    with pytest.raises(HTTPException):
        sec.require_api_key("segredo")


def test_cors_default_nao_e_wildcard():
    assert "*" not in sec.cors_origins()


def test_middleware_adiciona_headers_defensivos(monkeypatch):
    monkeypatch.setenv("RAG_ENABLE_HSTS", "1")
    middleware = sec.SecurityHeadersMiddleware(lambda scope, receive, send: None)
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})

    async def call_next(_request):
        return Response("ok")

    response = asyncio.run(middleware.dispatch(request, call_next))
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "object-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["strict-transport-security"].startswith("max-age=")


# ── Rate limiting ─────────────────────────────────────────────────────────────

def test_rate_limit_excedido_429(monkeypatch):
    monkeypatch.setenv("RAG_RATE_LIMIT", "2")
    monkeypatch.setenv("RAG_RATE_WINDOW", "60")
    req = _fake_request()
    sec.enforce_rate_limit(req)
    sec.enforce_rate_limit(req)
    with pytest.raises(HTTPException) as exc:
        sec.enforce_rate_limit(req)
    assert exc.value.status_code == 429


def test_rate_limit_por_ip_isolado(monkeypatch):
    monkeypatch.setenv("RAG_RATE_LIMIT", "1")
    sec.enforce_rate_limit(_fake_request("10.0.0.1"))
    # IP diferente não é afetado pelo limite do primeiro.
    sec.enforce_rate_limit(_fake_request("10.0.0.2"))
    with pytest.raises(HTTPException):
        sec.enforce_rate_limit(_fake_request("10.0.0.1"))


def test_rate_limit_zero_desliga(monkeypatch):
    monkeypatch.setenv("RAG_RATE_LIMIT", "0")
    req = _fake_request()
    for _ in range(10):
        sec.enforce_rate_limit(req)  # nunca levanta
