import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from comparacao import common, run
from simple_rag.rag import SimpleRAG, Chunk


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


def edit_index(mutate):
    """Altera o índice e mantém as duas pastas idênticas, como o `preparar` faz."""
    source = run.INDEX_PATHS["simple_rag"]
    payload = json.loads(source.read_text(encoding="utf-8"))
    mutate(payload)
    for path in run.INDEX_PATHS.values():
        path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def prepared(monkeypatch, tmp_path):
    settings = common.config()
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "fonte.txt").write_text("Indústria paulista em 2023.", encoding="utf-8")
    settings["corpus"] = str(corpus)
    settings["top_k"] = 1
    settings["reranker"] = ""  # sem modelo real nos testes
    settings["baseline_extra_slots"] = 0  # testes de reserva ligam explicitamente
    settings["ontology_filter"] = False
    settings["structured_lookup"] = False  # testes específicos ligam e usam um substituto
    monkeypatch.setattr(common, "config", lambda: settings)
    monkeypatch.setattr(run, "config", lambda: settings)
    artifacts = tmp_path / "artefatos"
    monkeypatch.setattr(run, "ARTIFACTS", artifacts)
    paths = {"simple_rag": tmp_path / "simple_rag" / "indice" / "index.json",
             "graph_rag": tmp_path / "graph_rag" / "indice" / "index.json"}
    monkeypatch.setattr(run, "INDEX_PATHS", paths)
    def embed(self, texts):
        return [[1, 0] if "preliminar" not in text else [0.8, 0.2] for text in texts]
    monkeypatch.setattr(SimpleRAG, "embed", embed)
    chunks = [Chunk("Indústria paulista em 2023.", "a.pdf", 1, 1,
                    {"node_id": "a", "source_file": "a.pdf", "page": 1, "type": "text", "chunk_id": 1}),
              Chunk("Indústria paulista em 2023: dado preliminar.", "b.pdf", 1, 1,
                    {"node_id": "b", "source_file": "b.pdf", "page": 1, "type": "text", "chunk_id": 1})]
    experiment = {"profile": common.fingerprint(settings), "corpus": run.corpus_snapshot(settings),
                  "pipeline": run.PIPELINE}
    rag = SimpleRAG(paths["simple_rag"], settings["embedding_model"], settings["llm_model"])
    rag.index_chunks(chunks, settings["chunk_size"], settings["chunk_overlap"], experiment)
    run.publish_indices(experiment, len(chunks))
    mock_llm = SimpleNamespace(complete=Mock(return_value=SimpleNamespace(text="Resposta com fontes.")))
    monkeypatch.setattr(common, "llm_model", lambda _: mock_llm)
    monkeypatch.setattr("simple_rag.rag.llm_model", lambda _: mock_llm)
    embedder = SimpleNamespace(get_query_embedding=Mock(return_value=[1, 0]))
    monkeypatch.setattr(common, "embedding_model", lambda _: embedder)
    return settings, mock_llm, embedder


def test_both_variants_share_vectors_initial_ranking_and_final_prompt(prepared):
    settings, llm, embedder = prepared
    question = "O que dizem as fontes sobre a indústria paulista em 2023?"
    baseline = run.compare(question, "simple_rag")
    graph = run.compare(question, "graph_rag")
    assert baseline["diagnostics"]["profile"] == graph["diagnostics"]["profile"]
    assert baseline["diagnostics"]["settings"] == graph["diagnostics"]["settings"] == settings
    assert baseline["diagnostics"]["initial_ids"] == graph["diagnostics"]["initial_ids"] == ["a"]
    assert [source["source"] for source in baseline["sources"]] == ["a.pdf"]
    # O grafo parte dos mesmos trechos iniciais; o pool de entidades raras (que trazia b.pdf aqui) foi retirado.
    assert {"a.pdf"} <= {source["source"] for source in graph["sources"]}
    assert embedder.get_query_embedding.call_count == 2
    prompts = [call.args[0] for call in llm.complete.call_args_list]
    assert prompts[0].split("Fontes de referência:")[0] == prompts[1].split("Fontes de referência:")[0]


def test_changed_corpus_aborts_before_model_call(prepared):
    settings, llm, _ = prepared
    (Path(settings["corpus"]) / "fonte.txt").write_text("Texto alterado.", encoding="utf-8")
    with pytest.raises(ValueError, match="Perfil ou corpus mudou"):
        run.compare("Pergunta", "simple_rag")
    llm.complete.assert_not_called()


def test_full_graph_expands_parent_without_changing_initial_ranking(prepared):
    settings, llm, _ = prepared
    edit_index(lambda payload: payload["chunks"][0]["metadata"].update(
        parent_id="parent:a", parent_text="Indústria paulista em 2023. Contexto literal adicional."))
    result = run.compare("O que dizem as fontes sobre a indústria paulista em 2023?", "graph_rag")
    assert result["diagnostics"]["initial_ids"] == ["a"]
    assert result["sources"][0]["metadata"]["context_strategy"] == "parent_child"
    assert "Contexto literal adicional." in llm.complete.call_args.args[0]


def test_full_graph_global_processes_all_sources_with_same_final_prompt(prepared):
    settings, llm, _ = prepared
    question = "Quais os principais temas do conjunto de documentos?"
    result = run.compare(question, "graph_rag")
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
        run.compare("Pergunta", "graph_rag")
    llm.complete.assert_not_called()


@pytest.fixture
def question_bank(prepared, monkeypatch, tmp_path):
    bank = tmp_path / "avaliacao"
    bank.mkdir()
    rows = [{"id": "D001", "categoria": "factual", "pergunta": "Indústria paulista em 2023?",
             "resposta_esperada": "GABARITO-SECRETO"},
            {"id": "D002", "categoria": "numerica", "pergunta": "O que diz o dado preliminar?",
             "resposta_esperada": "GABARITO-SECRETO"}]
    (bank / "desenvolvimento.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
    monkeypatch.setattr(run, "QUESTIONS", bank)
    return prepared


def test_batch_loads_index_and_graph_once_and_sends_only_question(question_bank, monkeypatch):
    settings, llm, embedder = question_bank
    loads = Mock(wraps=SimpleRAG.load_index)
    monkeypatch.setattr(SimpleRAG, "load_index", lambda self: loads(self))
    graph_class = run.REGISTRY["graph_rag"]
    built = Mock(side_effect=graph_class)
    built.graph_extraction = graph_class.graph_extraction
    monkeypatch.setitem(run.REGISTRY, "graph_rag", built)
    result = run.evaluate("desenvolvimento", "lote")
    assert result["executadas"] == 4 and result["erros"] == []
    assert loads.call_count == 1
    assert built.call_count == 1
    # Um ranking inicial por pergunta, compartilhado pelas duas versões.
    assert embedder.get_query_embedding.call_count == 2
    assert all("GABARITO-SECRETO" not in call.args[0] and "factual" not in call.args[0]
               for call in llm.complete.call_args_list)
    output = run.ARTIFACTS / "resultados" / "lote"
    manifest = json.loads((output / "manifesto.json").read_text(encoding="utf-8"))
    assert manifest["profile"] == common.fingerprint(settings)
    simple = json.loads((output / "D001_simple_rag.json").read_text(encoding="utf-8"))
    graph = json.loads((output / "D001_graph_rag.json").read_text(encoding="utf-8"))
    assert simple["diagnostics"]["initial_ids"] == graph["diagnostics"]["initial_ids"]
    assert "resposta_esperada" not in simple and "categoria" not in simple


def test_batch_resume_keeps_completed_and_rejects_other_profile(question_bank):
    settings, llm, _ = question_bank
    run.evaluate("desenvolvimento", "lote", ["D001"])
    calls = llm.complete.call_count
    output = run.ARTIFACTS / "resultados" / "lote"
    failed = output / "D001_graph_rag.json"
    failed.write_text(json.dumps({"erro": "falha anterior"}), encoding="utf-8")
    result = run.evaluate("desenvolvimento", "lote", ["D001"])
    assert result["mantidas"] == 1 and result["executadas"] == 1
    assert llm.complete.call_count > calls
    assert "erro" not in json.loads(failed.read_text(encoding="utf-8"))
    settings["llm_model"] = "modelo-alterado"
    with pytest.raises(ValueError, match="outro perfil"):
        run.evaluate("desenvolvimento", "lote", ["D001"])


def test_batch_rejects_unknown_ids_and_paths(question_bank):
    with pytest.raises(ValueError, match="D999"):
        run.evaluate("desenvolvimento", "lote", ["D999"])
    with pytest.raises(ValueError, match="nome de uma pasta"):
        run.evaluate("desenvolvimento", "../fora")


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
    paths = {"simple_rag": tmp_path / "simple_rag" / "indice" / "index.json",
             "graph_rag": tmp_path / "graph_rag" / "indice" / "index.json"}
    monkeypatch.setattr(run, "INDEX_PATHS", paths)
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
    stored = json.loads(paths["simple_rag"].read_text(encoding="utf-8"))
    assert stored["chunks"][0]["metadata"]["node_id"] == "id"
    # Vetores calculados uma vez: as duas pastas têm os mesmos bytes e o hash é registrado.
    assert paths["graph_rag"].read_bytes() == paths["simple_rag"].read_bytes()
    assert result["index_sha256"] == run.index_digest(paths["graph_rag"])
    for folder in ("simple_rag", "graph_rag"):
        manifest = json.loads((tmp_path / folder / "indice" / "manifesto.json").read_text(encoding="utf-8"))
        assert manifest["sha256"] == result["index_sha256"] and manifest["pipeline"] == run.PIPELINE


def test_factories_apply_same_embedding_and_generation_parameters(monkeypatch):
    # A paridade com a indexação do aplicativo vale para o provedor local.
    local = {**common.config(), "embedding_provider": "huggingface", "embedding_model": "BAAI/bge-m3"}
    monkeypatch.setattr(common, "config", lambda: local)
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


def test_openai_embedding_uses_profile_model_and_requires_key(monkeypatch):
    remote = {**common.config(), "embedding_provider": "openai", "embedding_model": "text-embedding-3-small"}
    monkeypatch.setattr(common, "config", lambda: remote)
    monkeypatch.delenv("RAG_EMBED_BATCH_SIZE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        common.embedding_model()
    from llama_index.embeddings import openai
    factory = Mock(return_value=SimpleNamespace())
    monkeypatch.setattr(openai, "OpenAIEmbedding", factory)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    common.embedding_model()
    assert factory.call_args.kwargs["model"] == "text-embedding-3-small"
    assert factory.call_args.kwargs["embed_batch_size"] == remote["embedding_batch_size"]


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
    with pytest.raises(ValueError, match="simple_rag, graph_rag"):
        run.compare("Pergunta", variant)
    profile.assert_not_called()


@pytest.mark.parametrize("invalid", ["missing", "duplicate", "metadata"])
def test_invalid_node_ids_rejected_before_model_loading(prepared, invalid):
    _, llm, embedder = prepared

    def break_ids(payload):
        if invalid == "metadata":
            payload["chunks"][0]["metadata"] = None
        elif invalid == "duplicate":
            payload["chunks"][1]["metadata"]["node_id"] = "a"
        else:
            payload["chunks"][0]["metadata"].pop("node_id")
    edit_index(break_ids)
    with pytest.raises(ValueError, match="node_id"):
        run.compare("Pergunta", "graph_rag")
    llm.complete.assert_not_called()
    embedder.get_query_embedding.assert_not_called()


def test_global_source_ids_exclude_empty_documents(prepared):
    edit_index(lambda payload: payload["chunks"][1].update(text="   "))
    result = run.compare("Quais os principais temas do conjunto de documentos?", "graph_rag")
    assert result["sources"][0]["metadata"]["source_ids"] == ["a"]


def test_parents_ablation_uses_parents_without_graph_neighbors(prepared):
    settings, llm, _ = prepared
    edit_index(lambda payload: payload["chunks"][0]["metadata"].update(
        parent_id="parent:a", parent_text="Indústria paulista em 2023. Contexto literal adicional."))
    result = run.compare("O que dizem as fontes sobre a indústria paulista em 2023?", "parent_rag")
    assert [source["source"] for source in result["sources"]] == ["a.pdf"]
    assert result["sources"][0]["metadata"]["context_strategy"] == "parent_child"
    assert "Contexto literal adicional." in llm.complete.call_args.args[0]


def test_graph_keeps_initial_ranking_and_reports_selection(prepared):
    result = run.compare("O que dizem as fontes sobre a indústria paulista em 2023?", "graph_rag")
    assert result["diagnostics"]["initial_ids"] == ["a"]
    assert result["sources"][0]["source"] == "a.pdf"
    selection = result["diagnostics"]["graph"]
    assert selection["threshold"] is None  # sem reranker nos testes
    assert {"candidates", "accepted"} <= set(selection)


def test_evaluate_defaults_to_frozen_versions_and_accepts_others(question_bank):
    result = run.evaluate("desenvolvimento", "padrao")
    assert result["executadas"] == 4
    output = run.ARTIFACTS / "resultados" / "padrao"
    assert sorted(path.name for path in output.glob("D001_*.json")) == ["D001_graph_rag.json", "D001_simple_rag.json"]
    result = run.evaluate("desenvolvimento", "ablacao", ["D001"], ["parent_rag", "graph_rag"])
    assert result["executadas"] == 2 and result["erros"] == []
    manifest = json.loads((run.ARTIFACTS / "resultados" / "ablacao" / "manifesto.json").read_text(encoding="utf-8"))
    assert manifest["runs"][-1]["variants"] == ["parent_rag", "graph_rag"]
    with pytest.raises(ValueError, match="Versões inválidas"):
        run.evaluate("desenvolvimento", "invalida", None, ["grafo"])


def test_simple_fills_extra_slots_with_next_ranked_chunks_and_keeps_initial_ids(prepared):
    settings, llm, _ = prepared
    settings["baseline_extra_slots"] = 1
    # O perfil faz parte da identidade do índice: regrava o hash nas duas pastas.
    edit_index(lambda payload: payload["experiment"].update(profile=common.fingerprint(settings)))
    question = "O que dizem as fontes sobre a indústria paulista em 2023?"
    result = run.compare(question, "simple_rag")
    assert result["diagnostics"]["initial_ids"] == ["a"]  # só os top_k são os iniciais
    assert result["diagnostics"]["reserve_ids"] == ["b"]
    assert [source["source"] for source in result["sources"]] == ["a.pdf", "b.pdf"]
    # O GraphRAG recebe a mesma reserva no diagnóstico, mas não a usa como extra.
    graph = run.compare(question, "graph_rag")
    assert graph["diagnostics"]["initial_ids"] == ["a"]
    assert graph["diagnostics"]["reserve_ids"] == ["b"]


def test_diverging_indices_abort_before_any_model_call(prepared):
    settings, llm, embedder = prepared
    run.INDEX_PATHS["graph_rag"].write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="divergem"):
        run.compare("Pergunta", "graph_rag")
    llm.complete.assert_not_called()
    embedder.get_query_embedding.assert_not_called()


def test_missing_index_in_one_folder_is_rejected(prepared):
    run.INDEX_PATHS["graph_rag"].unlink()
    with pytest.raises(ValueError, match="não encontrado"):
        run.compare("Pergunta", "simple_rag")


def test_simple_variant_uses_no_graph_module():
    import inspect
    from comparacao.variants import SimpleVariant
    source = inspect.getsource(SimpleVariant)
    for forbidden in ("graph_retriever", "graph_indexing", "GraphRetriever", "community_search",
                      "inject_deterministic_triplets", "SimplePropertyGraphStore"):
        assert forbidden not in source
    assert SimpleVariant.graph_extraction == "disabled"


def test_pipeline_version_and_profile_defaults():
    assert run.PIPELINE.endswith("-v4")
    assert set(run.INDEX_PATHS) == {"simple_rag", "graph_rag"}
    settings = common.config()
    assert settings["baseline_extra_slots"] == 6 and settings["ontology_filter"] is True


def test_implementation_is_chosen_by_variants_and_graph_needs_graph_rag():
    assert common.implementation_for(["simple_rag"]) == "simple_rag"
    assert common.implementation_for(["simple_rag", "parent_rag"]) == "simple_rag"
    assert common.implementation_for(["simple_rag", "graph_rag"]) == "graph_rag"
    assert common.implementation_for(["graph_rag"]) == "graph_rag"
    assert common.implementation_for([]) == "graph_rag"
    with pytest.raises(ValueError, match="Implementação inválida"):
        common.use_implementation("outra")


def test_structured_rows_enter_the_shared_ranking_and_are_sent_to_both_versions(prepared, monkeypatch):
    import sys
    from llama_index.core.schema import NodeWithScore, TextNode
    settings, llm, _ = prepared
    settings["structured_lookup"] = True
    edit_index(lambda payload: payload["experiment"].update(profile=common.fingerprint(settings)))

    class FakeLookup:
        def __init__(self, directory):
            self.directory = directory

        def retrieve(self, question, limit=8):
            node = TextNode(id_="structured:linha-9", text="Município: Exemplo\nPIB: 123",
                            metadata={"type": "table", "source_file": "tabela.csv", "page": "linha 9", "row": 9,
                                      "retrieval_method": "structured_exact"})
            return [NodeWithScore(node=node, score=1.0)]

    monkeypatch.setitem(sys.modules, "structured_lookup", SimpleNamespace(StructuredLookup=FakeLookup))
    question = "O que dizem as fontes sobre a indústria paulista em 2023?"
    for variant in ("simple_rag", "graph_rag"):
        result = run.compare(question, variant)
        # A linha exata vai à frente e os trechos iniciais (top_k=1) passam a incluí-la, nas duas versões.
        assert result["diagnostics"]["initial_ids"] == ["structured:linha-9"]
        assert result["sources"][0]["source"] == "tabela.csv"
        assert "Município: Exemplo" in llm.complete.call_args.args[0]
