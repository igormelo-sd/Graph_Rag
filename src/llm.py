"""
rag_core/llm.py — fábrica única de LLM (OpenAI ou provedores compatíveis).

Todo o projeto fala com a API no formato OpenAI. Este módulo concentra a
escolha do provedor para que trocar de LLM seja só configuração de ambiente —
sem tocar em nenhuma engine. Os embeddings continuam locais (HuggingFace
bge-m3) e não passam por aqui.

Configuração por ambiente
--------------------------
    RAG_LLM_PROVIDER   "maritaca" (padrão) | "openai" | "ollama"
    RAG_LLM_MODEL      sobrescreve o modelo de síntese
    RAG_INTERP_MODEL   sobrescreve o modelo de interpretação/crítica
    RAG_POPUP_MODEL    sobrescreve o modelo das explicações de citações
    RAG_LLM_BASE_URL   sobrescreve a base URL do provedor
    RAG_LLM_API_KEY    sobrescreve a chave (senão usa a chave padrão do provedor)

Maritaca usa a chave `MARITACA_API_KEY`; OpenAI usa `OPENAI_API_KEY`.
Ollama roda localmente e não exige chave.

Dois consumidores
-----------------
- `make_llm(...)`          → objeto LLM do LlamaIndex (startups, processing).
                             Para provedores com base URL própria, registra o
                             modelo (ex.: "sabia-4") no catálogo do LlamaIndex
                             e usa a classe `OpenAI` base — sem depender do
                             pacote `openai-like`, cuja versão colide com o
                             `llama-index-llms-openai` já resolvido pelo core.
- `openai_client_kwargs()` → kwargs para `openai.OpenAI`/`AsyncOpenAI` cru
                             (agentic, self-rag, raptor, orchestrator analyzer).
"""
from __future__ import annotations

import os

_PROVIDERS: dict[str, dict] = {
    "maritaca": {
        "base_url": "https://chat.maritaca.ai/api",
        "key_env": "MARITACA_API_KEY",
        "main_model": "sabia-4",
        "interp_model": "sabia-4",
        "popup_model": "sabiazinho-4",
        "context_window": 128000,
    },
    "openai": {
        "base_url": None,  # SDK usa o endpoint padrão da OpenAI
        "key_env": "OPENAI_API_KEY",
        "main_model": "gpt-5-chat-latest",
        "interp_model": "gpt-5-mini",
        "popup_model": "gpt-5-mini",
        "context_window": 128000,
    },
    "ollama": {
        "base_url": "http://127.0.0.1:11434/v1",
        "key_env": "OLLAMA_API_KEY",
        # O cliente OpenAI exige um valor, embora o Ollama o ignore.
        "default_api_key": "ollama",
        "main_model": "qwen3:4b-instruct",
        "interp_model": "qwen3:4b-instruct",
        "popup_model": "qwen3:4b-instruct",
        "context_window": 32768,
    },
}


def provider_name() -> str:
    return os.getenv("RAG_LLM_PROVIDER", "maritaca").lower()


def _cfg() -> dict:
    cfg = dict(_PROVIDERS.get(provider_name(), _PROVIDERS["openai"]))
    if os.getenv("RAG_LLM_BASE_URL"):
        cfg["base_url"] = os.getenv("RAG_LLM_BASE_URL")
    cfg["api_key"] = (
        os.getenv("RAG_LLM_API_KEY")
        or os.getenv(cfg["key_env"])
        or cfg.get("default_api_key")
    )
    cfg["main_model"] = os.getenv("RAG_LLM_MODEL", cfg["main_model"])
    cfg["interp_model"] = os.getenv("RAG_INTERP_MODEL", cfg["interp_model"])
    cfg["popup_model"] = os.getenv("RAG_POPUP_MODEL", cfg["popup_model"])
    return cfg


def main_model() -> str:
    return _cfg()["main_model"]


def interp_model() -> str:
    return _cfg()["interp_model"]


def popup_model() -> str:
    """Modelo leve dedicado à redação das explicações de citações numéricas."""
    return _cfg()["popup_model"]


def llm_concurrency(default: int = 4) -> int:
    """Limite de chamadas paralelas; Ollama local usa uma por vez por padrão."""
    raw = os.getenv("RAG_LLM_CONCURRENCY")
    if raw:
        try:
            return max(1, min(int(raw), 16))
        except ValueError:
            pass
    return 1 if provider_name() == "ollama" else default


def require_api_key() -> None:
    """Valida a chave do provedor ativo; lança EnvironmentError com dica clara."""
    cfg = _cfg()
    if not cfg["api_key"]:
        env = "RAG_LLM_API_KEY" if os.getenv("RAG_LLM_API_KEY") is not None else cfg["key_env"]
        raise EnvironmentError(
            f"Chave do provedor '{provider_name()}' não encontrada. "
            f"Defina {env} no .env (ou troque RAG_LLM_PROVIDER)."
        )


def openai_client_kwargs() -> dict:
    """kwargs para instanciar `openai.OpenAI(**kwargs)` / `AsyncOpenAI(**kwargs)`."""
    cfg = _cfg()
    kwargs: dict = {"api_key": cfg["api_key"]}
    if cfg["base_url"]:
        kwargs["base_url"] = cfg["base_url"]
    return kwargs


def _register_model(model: str, context_window: int) -> None:
    """
    Registra um modelo fora do catálogo OpenAI (ex.: "sabia-4") no LlamaIndex,
    para a classe `OpenAI` base aceitá-lo sem exigir o pacote `openai-like`.
    Idempotente (`setdefault`).
    """
    from llama_index.llms.openai import utils as _ou

    _ou.ALL_AVAILABLE_MODELS.setdefault(model, context_window)
    _ou.CHAT_MODELS.setdefault(model, context_window)


def make_llm(
    *,
    interp: bool = False,
    temperature: float = 0.0,
    timeout: float = 60.0,
    model: str | None = None,
):
    """
    Cria o LLM do LlamaIndex para o provedor configurado.

    interp=True usa o modelo de interpretação/crítica (mais leve, quando o
    provedor distingue); caso contrário, o modelo de síntese.
    """
    from llama_index.llms.openai import OpenAI

    cfg = _cfg()
    mdl = model or (cfg["interp_model"] if interp else cfg["main_model"])

    if cfg["base_url"]:
        # Provedor compatível (Maritaca): registra o modelo e aponta a base URL.
        _register_model(mdl, cfg["context_window"])
        return OpenAI(
            model=mdl,
            api_base=cfg["base_url"],
            api_key=cfg["api_key"],
            temperature=temperature,
            timeout=timeout,
        )

    return OpenAI(model=mdl, api_key=cfg["api_key"], temperature=temperature, timeout=timeout)
