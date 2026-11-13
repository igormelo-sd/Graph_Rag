"""Embedding OpenAI nos aplicativos: o mesmo do perfil da comparação, sem baixar modelo do HuggingFace."""
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import indexing


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(indexing, "_EMBED_INSTANCE", None)
    monkeypatch.setattr(indexing, "_EMBED_IDENTITY", None)
    monkeypatch.setattr(indexing, "Settings", SimpleNamespace())
    for name in ("RAG_EMBED_MODEL", "RAG_EMBED_BATCH_SIZE", "RAG_EMBED_DEVICE"):
        monkeypatch.delenv(name, raising=False)


def test_openai_provider_uses_the_openai_model_and_not_the_local_default(monkeypatch):
    factory = Mock(return_value=SimpleNamespace())
    monkeypatch.setitem(sys.modules, "llama_index.embeddings.openai", SimpleNamespace(OpenAIEmbedding=factory))
    monkeypatch.setenv("RAG_EMBED_PROVIDER", "openai")
    assert indexing._embed_config()["model"] == "text-embedding-3-small"
    indexing.setup_embeddings()
    assert factory.call_args.kwargs["model"] == "text-embedding-3-small"
    indexing.setup_embeddings()                       # mesma identidade: não recria o cliente
    assert factory.call_count == 1
    monkeypatch.setenv("RAG_EMBED_MODEL", "text-embedding-3-large")
    indexing.setup_embeddings()
    assert factory.call_args.kwargs["model"] == "text-embedding-3-large" and factory.call_count == 2


def test_default_provider_stays_local_and_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.delenv("RAG_EMBED_PROVIDER", raising=False)
    assert indexing._embed_config()["provider"] == "huggingface" and indexing._embed_config()["model"] == "BAAI/bge-m3"
    monkeypatch.setenv("RAG_EMBED_PROVIDER", "outro")
    with pytest.raises(ValueError, match="huggingface, ollama ou openai"):
        indexing.setup_embeddings()
