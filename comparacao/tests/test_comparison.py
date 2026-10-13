import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from comparacao import common, run
from rag_simples.rag import SimpleRAG, Chunk


@pytest.fixture(autouse=True)
def restore_environment():
    previous = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(previous)


def test_strict_profile_removes_local_model_and_retrieval_drift(monkeypatch):
    monkeypatch.setenv("RAG_LLM_MODEL", "outro-modelo")
    monkeypatch.setenv("RAG_EMBED_MODEL", "outro-embedding")
    monkeypatch.setenv("RAG_BGE_RERANK", "1")
    monkeypatch.setenv("RAG_ENTITY_CONTEXT_DEPTH", "2")
    monkeypatch.setenv("RAG_LLM_BASE_URL", "http://outro-endpoint")
    settings = common.apply_profile(strict=True)
    import os
    assert os.environ["RAG_LLM_MODEL"] == settings["llm_model"]
    assert os.environ["RAG_EMBED_MODEL"] == settings["embedding_model"]
    assert os.environ["RAG_BGE_RERANK"] == "0"
    assert os.environ["RAG_ENTITY_CONTEXT_DEPTH"] == str(settings["entity_context_depth"])
    assert "RAG_LLM_BASE_URL" not in os.environ


@pytest.fixture
def prepared(monkeypatch, tmp_path):
    settings = common.config()
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "fonte.txt").write_text("Indústria paulista em 2023.", encoding="utf-8")
    settings["corpus"] = str(corpus)
    settings["top_k"] = 1
    monkeypatch.setattr(common, "config", lambda: settings)
    monkeypatch.setattr(run, "config", lambda: settings)
    artifacts = tmp_path / "artefatos"
    monkeypatch.setattr(run, "ARTIFACTS", artifacts)
    def embed(self, texts):
        return [[1, 0] if "preliminar" not in text else [0.8, 0.2] for text in texts]
    monkeypatch.setattr(SimpleRAG, "embed", embed)
    chunks = [Chunk("Indústria paulista em 2023.", "a.pdf", 1, 1,
                    {"node_id": "a", "source_file": "a.pdf", "page": 1, "type": "text", "chunk_id": 1}),
              Chunk("Indústria paulista em 2023: dado preliminar.", "b.pdf", 1, 1,
                    {"node_id": "b", "source_file": "b.pdf", "page": 1, "type": "text", "chunk_id": 1})]
    experiment = {"profile": common.fingerprint(settings), "corpus": run.corpus_snapshot(settings),
                  "pipeline": "shared-graph-processing-v1"}
    rag = SimpleRAG(artifacts / "index.json", settings["embedding_model"], settings["llm_model"])
    rag.index_chunks(chunks, settings["chunk_size"], settings["chunk_overlap"], experiment)
    mock_llm = SimpleNamespace(complete=Mock(return_value=SimpleNamespace(text="Resposta com fontes.")))
    monkeypatch.setattr(common, "llm_model", lambda _: mock_llm)
    monkeypatch.setattr("rag_simples.rag.llm_model", lambda _: mock_llm)
    embedder = SimpleNamespace(get_query_embedding=Mock(return_value=[1, 0]))
    monkeypatch.setattr(common, "embedding_model", lambda _: embedder)
    return settings, mock_llm, embedder


def test_both_variants_share_vectors_initial_ranking_and_final_prompt(prepared):
    settings, llm, embedder = prepared
    question = "O que dizem as fontes sobre a indústria paulista em 2023?"
    baseline = run.compare(question, "rag_simples")
    graph = run.compare(question, "graphrag")
    assert baseline["diagnostics"]["profile"] == graph["diagnostics"]["profile"]
    assert baseline["diagnostics"]["settings"] == graph["diagnostics"]["settings"] == settings
    assert baseline["diagnostics"]["initial_ids"] == graph["diagnostics"]["initial_ids"] == ["a"]
    assert [source["source"] for source in baseline["sources"]] == ["a.pdf"]
    assert {source["source"] for source in graph["sources"]} == {"a.pdf", "b.pdf"}
    assert embedder.get_query_embedding.call_count == 2
    prompts = [call.args[0] for call in llm.complete.call_args_list]
    assert prompts[0].split("Fontes de referência:")[0] == prompts[1].split("Fontes de referência:")[0]


def test_changed_corpus_aborts_before_model_call(prepared):
    settings, llm, _ = prepared
    (Path(settings["corpus"]) / "fonte.txt").write_text("Texto alterado.", encoding="utf-8")
    with pytest.raises(ValueError, match="Perfil ou corpus mudou"):
        run.compare("Pergunta", "rag_simples")
    llm.complete.assert_not_called()


def test_full_graph_expands_parent_without_changing_initial_ranking(prepared):
    settings, llm, _ = prepared
    path = run.ARTIFACTS / "index.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["chunks"][0]["metadata"].update(
        parent_id="parent:a", parent_text="Indústria paulista em 2023. Contexto literal adicional.")
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = run.compare("O que dizem as fontes sobre a indústria paulista em 2023?", "graphrag")
    assert result["diagnostics"]["initial_ids"] == ["a"]
    assert result["sources"][0]["metadata"]["context_strategy"] == "parent_child"
    assert "Contexto literal adicional." in llm.complete.call_args.args[0]


def test_full_graph_global_processes_all_sources_with_same_final_prompt(prepared):
    settings, llm, _ = prepared
    question = "Quais os principais temas do conjunto de documentos?"
    result = run.compare(question, "graphrag")
    assert result["diagnostics"]["initial_ids"] == ["a"]
    assert result["diagnostics"]["all_communities_processed"] is True
    assert result["diagnostics"]["communities"] > 0
    assert result["sources"][0]["metadata"]["source_ids"] == ["a", "b"]
    assert llm.complete.call_count >= 3  # Resumo, consolidação e síntese final.
    final_prompt = llm.complete.call_args.args[0]
    context, _ = common.pack_results(result["sources"], settings["context_tokens"])
    assert final_prompt == common.answer_prompt(question, context)


def test_changed_profile_aborts_before_model_call(prepared):
    settings, llm, _ = prepared
    settings["llm_model"] = "modelo-alterado"
    with pytest.raises(ValueError, match="Perfil ou corpus mudou"):
        run.compare("Pergunta", "graphrag")
    llm.complete.assert_not_called()


def test_context_budget_preserves_whole_chunks():
    results = [{"text": "X" * 1000, "source": "a.pdf", "page": 1},
               {"text": "Trecho curto.", "source": "b.pdf", "page": 2}]
    text, used = common.pack_results(results, budget=50)
    assert "XXXX" not in text
    assert used == [results[1]]
    assert "[1] Fonte: b.pdf" in text


def test_query_embedding_uses_query_method_not_document_method():
    rag = SimpleRAG(Path("unused"), "fake", "fake")
    rag._embedder = SimpleNamespace(get_query_embedding=Mock(return_value=[3, 0]),
                                    get_text_embedding_batch=Mock(return_value=[[0, 4]]))
    assert rag.embed_query("pergunta") == [1, 0]
    assert rag.embed(["documento"]) == [[0, 1]]
    rag._embedder.get_query_embedding.assert_called_once_with("pergunta")
    rag._embedder.get_text_embedding_batch.assert_called_once_with(["documento"])


def test_preparation_uses_one_shared_ingestion_and_embedding_pass(monkeypatch, tmp_path):
    common.graph_modules()
    from llama_index.core.schema import Document, TextNode
    import ingestion
    import processing
    settings = common.config()
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "fonte.txt").write_text("Texto literal.", encoding="utf-8")
    settings["corpus"] = str(corpus)
    monkeypatch.setattr(common, "config", lambda: settings)
    monkeypatch.setattr(run, "ARTIFACTS", tmp_path / "output")
    load = Mock(return_value=[Document(text="Texto literal.")])
    process = Mock(return_value=[TextNode(id_="id", text="Texto literal.",
        metadata={"node_id": "id", "source_file": "fonte.txt", "page": 1, "chunk_id": 1, "type": "text"})])
    monkeypatch.setattr(ingestion, "load_documents", load)
    monkeypatch.setattr(processing, "process_documents", process)
    monkeypatch.setattr(SimpleRAG, "embed", lambda self, texts: [[1, 0] for _ in texts])
    result = run.prepare()
    assert result["chunks"] == 1
    load.assert_called_once_with(str(corpus), save_output=False)
    process.assert_called_once()
    stored = json.loads((run.ARTIFACTS / "index.json").read_text(encoding="utf-8"))
    assert stored["chunks"][0]["metadata"]["node_id"] == "id"


def test_factories_apply_same_embedding_and_generation_parameters(monkeypatch):
    settings = common.apply_profile(strict=True)
    common.graph_modules()
    import indexing
    from llama_index.embeddings import huggingface
    factory = Mock(return_value=SimpleNamespace())
    monkeypatch.setattr(huggingface, "HuggingFaceEmbedding", factory)
    common.embedding_model()
    common_kwargs = factory.call_args.kwargs
    monkeypatch.setattr(indexing, "HuggingFaceEmbedding", factory)
    monkeypatch.setattr(indexing, "Settings", SimpleNamespace())
    indexing.setup_embeddings()
    assert factory.call_args.kwargs == common_kwargs
    assert common_kwargs["normalize"] is True
    assert common_kwargs["device"] == settings["embedding_device"]
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    llm = common.llm_model()
    assert llm.model == settings["llm_model"]
    assert llm.temperature == settings["temperature"]
    assert llm.max_tokens == settings["max_output_tokens"]


def test_embedding_parameter_changes_invalidate_graph_manifest(monkeypatch):
    common.graph_modules()
    from index_manifest import _pipeline_fingerprint
    common.apply_profile(strict=True)
    original = _pipeline_fingerprint()
    monkeypatch.setenv("RAG_EMBED_NORMALIZE", "0")
    assert _pipeline_fingerprint() != original
    monkeypatch.setenv("RAG_EMBED_NORMALIZE", "1")
    monkeypatch.setenv("RAG_EMBED_MAX_LENGTH", "512")
    assert _pipeline_fingerprint() != original


@pytest.mark.parametrize("variant", ["simples", "grafo", "grafo_completo", "", None])
def test_removed_variants_fail_before_configuration(monkeypatch, variant):
    profile = Mock(side_effect=AssertionError("Não deve carregar o perfil"))
    monkeypatch.setattr(run, "apply_profile", profile)
    with pytest.raises(ValueError, match="rag_simples ou graphrag"):
        run.compare("Pergunta", variant)
    profile.assert_not_called()


@pytest.mark.parametrize("invalid", ["missing", "duplicate", "metadata"])
def test_invalid_node_ids_rejected_before_model_loading(prepared, invalid):
    _, llm, embedder = prepared
    path = run.ARTIFACTS / "index.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if invalid == "metadata":
        payload["chunks"][0]["metadata"] = None
    elif invalid == "duplicate":
        payload["chunks"][1]["metadata"]["node_id"] = "a"
    else:
        payload["chunks"][0]["metadata"].pop("node_id")
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="node_id"):
        run.compare("Pergunta", "graphrag")
    llm.complete.assert_not_called()
    embedder.get_query_embedding.assert_not_called()


def test_global_source_ids_exclude_empty_documents(prepared):
    path = run.ARTIFACTS / "index.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["chunks"][1]["text"] = "   "
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = run.compare("Quais os principais temas do conjunto de documentos?", "graphrag")
    assert result["sources"][0]["metadata"]["source_ids"] == ["a"]
