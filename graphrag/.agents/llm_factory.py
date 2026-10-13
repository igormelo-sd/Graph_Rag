"""
LLM Factory — cria clientes e modelos compatíveis com llama-index de forma automática.

Funcionalidades principais:
- Lê RAG_LLM_PROVIDER do ambiente (.env) e prioriza o provedor correspondente.
- Fallback de chaves: OPENAI_API_KEY → OPENAI_API_KEY_2 → OPENROUTER_API_KEY.
- Detecta 429/credit_balance_exhausted e passa para a próxima chave automaticamente.
- Retorna LLMs llama-index Sync para query, enriquecimento e indexação.
- Retorna AsyncOpenAI para engines assíncronos.
- Usado por todos os módulos RAG para manter o sistema resiliente sem loops por falta de créditos.

Variáveis de ambiente:
    RAG_LLM_PROVIDER:     "openai", "openrouter", "auto". Padrão "auto".
    RAG_LLM_MODEL:        modelo principal (ex.: "gpt-4o-mini" na OpenAI).
    RAG_INTERP_MODEL:     modelo leve (interpreter/rerank/enriquecimento) (ex.: "gpt-4o-mini").
    RAG_INGEST_LLM_ENRICHMENT: 0|1. Controla enriquecimento de metadados em processing.py.

Estrutura do diretório: .agents/ (copiado para cada RAG no Dockerfile).
"""

import os
from typing import Optional, Tuple, List

from llama_index.llms.openai import OpenAI
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from openai import AsyncOpenAI, RateLimitError, APIStatusError
from llama_index.core import Settings
from llama_index.core.base.llms.types import LLMMetadata, MessageRole
from llama_index.llms.openai.utils import O1_MODELS

# Provedores disponíveis (conforme usado no .env)
PROVIDERS = {
    "openai": {"name": "OpenAI", "prefix": "openai"},
    "openrouter": {"name": "OpenRouter", "prefix": "openrouter"},
    "auto": {"name": "Auto", "prefix": "auto"},
}

# Mapeamento de provedor -> API URL (endpoints OpenAI-compatíveis)
PROVIDER_URLS = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

# Contexto padrão para modelos não cadastrados no registry do llama-index.
DEFAULT_CONTEXT_WINDOW = 8000


class LLMKeyNotFoundError(Exception):
    pass


class _OpenAICompat(OpenAI):
    """
    OpenAI() do llama-index com `metadata` próprio.

    O `metadata` da classe base chama `openai_modelname_to_contextsize(self.model)`,
    que falha com modelos fora do registry OpenAI.
    Este subclass fornece um contexto fixo e is_chat_model=True, contornando o
    registry sem instalar integrações adicionais.
    """

    def __init__(self, *args, compat_context_window: int = DEFAULT_CONTEXT_WINDOW, **kwargs):
        super().__init__(*args, **kwargs)
        self._compat_context_window = compat_context_window

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(
            context_window=self._compat_context_window,
            num_output=self.max_tokens or -1,
            is_chat_model=True,
            is_function_calling_model=False,
            model_name=self.model,
            system_role=MessageRole.USER if self.model in O1_MODELS else MessageRole.SYSTEM,
        )


class LLMFactory:
    """Factory simples, thread-safe, que gerencia chaves do ambiente e fallbacks."""

    def __init__(self):
        self._provider = os.getenv("RAG_LLM_PROVIDER", "auto").strip().lower()
        if self._provider not in PROVIDERS:
            raise ValueError(f"RAG_LLM_PROVIDER inválido: {self._provider}. Escolha um de {list(PROVIDERS.keys())}")

        self._urls = self._determine_urls()
        self._failure_counts = {}

    # ── Utilidades ───────────────────────────────────────────────────────────

    def _determine_urls(self) -> List[str]:
        """Retorna a lista de URLs de API candidatas com base no provedor fornecido."""
        if self._provider == "auto":
            return [PROVIDER_URLS[p] for p in ["openai", "openrouter"] if p in PROVIDER_URLS]
        return [PROVIDER_URLS[self._provider]]

    def _load_keys(self) -> List[Tuple[str, str, str]]:
        """Lista de tuplas (provider_name, base_url, api_key). Ordem de preferência de chave."""
        candidates = []
        if os.getenv("OPENROUTER_API_KEY"):
            candidates.append(("openrouter", PROVIDER_URLS["openrouter"], os.getenv("OPENROUTER_API_KEY")))
        if os.getenv("OPENAI_API_KEY_2"):
            candidates.append(("openai", PROVIDER_URLS["openai"], os.getenv("OPENAI_API_KEY_2")))
        if os.getenv("OPENAI_API_KEY"):
            candidates.append(("openai", PROVIDER_URLS["openai"], os.getenv("OPENAI_API_KEY")))
        return candidates

    def _ordered_candidates(self) -> List[Tuple[str, str, str]]:
        """Candidatas com o provedor configurado em RAG_LLM_PROVIDER tentado primeiro."""
        candidates = self._load_keys()
        if self._provider != "auto":
            candidates = sorted(candidates, key=lambda c: 0 if c[0] == self._provider else 1)
        return candidates

    def _increment_failure(self, key: str) -> None:
        self._failure_counts[key] = self._failure_counts.get(key, 0) + 1

    def _reset_failures(self, key: str) -> None:
        self._failure_counts.pop(key, None)

    def _should_skip(self, key: str) -> bool:
        """Pula chaves após 2 falhas consecutivas."""
        return self._failure_counts.get(key, 0) >= 2

    @staticmethod
    def _is_quota_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return "429" in text or "credit_balance_exhausted" in text or "insufficient_quota" in text

    @staticmethod
    def _strip_provider_prefix(name: str) -> str:
        """Remove prefixos tipo 'openai/' que o registry do llama-index rejeita."""
        if name and "/" in name:
            return name.split("/")[-1]
        return name

    @staticmethod
    def _is_openai_name(name: str) -> bool:
        n = (name or "").lower()
        return n.startswith(("gpt", "o1", "o3", "o4", "chatgpt"))

    def _resolve_model(self, provider: str, requested: Optional[str]) -> str:
        requested = self._strip_provider_prefix(requested)
        # openai / openrouter — só aceitam nomes OpenAI válidos
        if not requested or not self._is_openai_name(requested):
            env_model = os.getenv("RAG_LLM_MODEL", "")
            if self._is_openai_name(env_model):
                return env_model
            return "gpt-4o-mini"
        return requested

    # ── LLM síncrono (llama-index) ───────────────────────────────────────────

    def get_llm(self, model: Optional[str] = None, temperature: float = 0.0, timeout: float = 60.0) -> OpenAI:
        """Retorna um LLM llama-index ativo, alternando pelas chaves/provedores."""
        for provider, url, key in self._ordered_candidates():
            if self._should_skip(key):
                continue
            m = self._resolve_model(provider, model)
            try:
                if provider == "openai":
                    llm = OpenAI(model=m, api_key=key, temperature=temperature, timeout=timeout)
                else:
                    llm = _OpenAICompat(
                        model=m, api_key=key, api_base=url,
                        temperature=temperature, timeout=timeout,
                    )
                self._reset_failures(key)
                return llm
            except Exception:
                self._increment_failure(key)
                continue

        raise LLMKeyNotFoundError("Nenhum LLM disponível após tentar todos os provedores.")

    # ── Cliente assíncrono (engines agentic/raptor) ──────────────────────────

    def get_async_client(self) -> AsyncOpenAI:
        """Retorna um AsyncOpenAI para o provedor preferido (endpoints OpenAI-compatíveis)."""
        for provider, url, key in self._ordered_candidates():
            if self._should_skip(key):
                continue
            try:
                base_url = None if provider == "openai" else url
                client = AsyncOpenAI(api_key=key, base_url=base_url, timeout=120.0)
                self._reset_failures(key)
                return client
            except RateLimitError as e:
                if self._is_quota_error(e):
                    self._increment_failure(key)
                    continue
                raise
            except APIStatusError as e:
                if self._is_quota_error(e):
                    self._increment_failure(key)
                    continue
                raise
            except Exception:
                self._increment_failure(key)
                continue

        raise LLMKeyNotFoundError("Não foi possível criar cliente assíncrono após todos os provedores.")

    # ── Embeddings ───────────────────────────────────────────────────────────

    def get_embedding_model(self) -> HuggingFaceEmbedding:
        """Retorna um modelo de embeddings robusto e local."""
        return HuggingFaceEmbedding(model_name="BAAI/bge-m3")

    @classmethod
    def get_instance(cls) -> "LLMFactory":
        if not hasattr(cls, "_instance"):
            cls._instance = cls()
        return cls._instance


# Singleton global usado por todos os módulos RAG
llm_factory = LLMFactory.get_instance()
