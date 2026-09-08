import llm


def test_maritaca_is_the_default_provider(monkeypatch):
    for name in (
        "RAG_LLM_PROVIDER",
        "RAG_LLM_MODEL",
        "RAG_INTERP_MODEL",
        "RAG_LLM_BASE_URL",
        "RAG_LLM_API_KEY",
        "MARITACA_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    assert llm.provider_name() == "maritaca"
    assert llm.main_model() == "sabia-4"
    assert llm.interp_model() == "sabia-4"
    assert llm._cfg()["base_url"] == "https://chat.maritaca.ai/api"
    assert llm._cfg()["context_window"] == 128000


def test_llm_environment_overrides_are_preserved(monkeypatch):
    monkeypatch.setenv("RAG_LLM_PROVIDER", "maritaca")
    monkeypatch.setenv("RAG_LLM_MODEL", "modelo-principal")
    monkeypatch.setenv("RAG_INTERP_MODEL", "modelo-interprete")
    monkeypatch.setenv("RAG_LLM_BASE_URL", "https://example.invalid/api")
    monkeypatch.setenv("RAG_LLM_API_KEY", "test-key")

    config = llm._cfg()

    assert config["main_model"] == "modelo-principal"
    assert config["interp_model"] == "modelo-interprete"
    assert config["base_url"] == "https://example.invalid/api"
    assert config["api_key"] == "test-key"


def test_ollama_uses_local_defaults_without_api_key(monkeypatch):
    monkeypatch.setenv("RAG_LLM_PROVIDER", "ollama")
    for name in (
        "RAG_LLM_MODEL",
        "RAG_INTERP_MODEL",
        "RAG_LLM_BASE_URL",
        "RAG_LLM_API_KEY",
        "OLLAMA_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    config = llm._cfg()

    assert config["base_url"] == "http://127.0.0.1:11434/v1"
    assert config["main_model"] == "qwen3:4b-instruct"
    assert config["interp_model"] == "qwen3:4b-instruct"
    assert config["api_key"] == "ollama"
    llm.require_api_key()


def test_ollama_limits_local_concurrency(monkeypatch):
    monkeypatch.setenv("RAG_LLM_PROVIDER", "ollama")
    monkeypatch.delenv("RAG_LLM_CONCURRENCY", raising=False)
    assert llm.llm_concurrency(default=8) == 1

    monkeypatch.setenv("RAG_LLM_CONCURRENCY", "2")
    assert llm.llm_concurrency(default=8) == 2
