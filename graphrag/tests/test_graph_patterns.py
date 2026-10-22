import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from llama_index.core.schema import Document, TextNode, NodeWithScore, MetadataMode
from llama_index.core.graph_stores import SimplePropertyGraphStore
from llama_index.core.graph_stores.types import EntityNode, Relation

from graph_indexing import _inject_domain_triplets, _inject_structural_triplets
from graph_retriever import GraphRetriever
from parent_context import prepare_parents, attach_parents, expand_parents
from community_search import CommunitySearch, detect_communities, is_global_question
from processing import process_documents
from analysis_engine import AnalysisEngine
from query_interpreter import interpret_query
from index_manifest import _pipeline_fingerprint


def node(identity, text, source="fonte.pdf", page=1):
    return TextNode(id_=identity, text=text,
        metadata={"type": "text", "source_file": source, "page": page, "chunk_id": 1})


def store_for(nodes):
    store = SimplePropertyGraphStore()
    _inject_structural_triplets(store, nodes)
    _inject_domain_triplets(store, nodes)
    return store


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch):
    monkeypatch.setenv("RAG_ONTOLOGY_ENABLE", "1")
    monkeypatch.setenv("RAG_INGEST_LLM_ENRICHMENT", "0")
    monkeypatch.setenv("RAG_GLOBAL_SEARCH", "1")
    monkeypatch.setenv("RAG_MAX_CONTEXT_TOKENS", "1000")
    monkeypatch.setenv("RAG_COMMUNITY_SUMMARY_CHARS", "200")
    monkeypatch.setenv("RAG_CHUNK_SIZE", "200")
    monkeypatch.setenv("RAG_CHUNK_OVERLAP", "20")
    monkeypatch.setenv("RAG_PARENT_SIZE", "600")


def test_entity_expansion_connects_documents_but_rejects_wrong_period():
    nodes = [node("seed", "PIB no Estado de São Paulo em 2023.", "primeiro.pdf"),
             node("related", "PIB no Estado de São Paulo em 2023: análise complementar.", "outro.pdf"),
             node("wrong", "PIB no Estado de São Paulo em 2022.", "antigo.pdf")]
    retriever = GraphRetriever(SimpleNamespace(property_graph_store=store_for(nodes)), None, use_llm=False)
    results = retriever.retrieve_entity_context([NodeWithScore(node=nodes[0])],
                                              "PIB no Estado de São Paulo em 2023")
    assert [item.node_id for item in results] == ["related"]
    paths = json.loads(results[0].metadata["graph_paths"])
    assert paths[0]["source"] == "seed"
    assert paths[-1]["source"] == "related"
    assert all(edge["semantic_status"] == "mention_only" for edge in paths)


def test_entity_expansion_respects_result_limit(monkeypatch):
    monkeypatch.setenv("RAG_ENTITY_CONTEXT_LIMIT", "2")
    nodes = [node(str(i), "Indústria no Estado de São Paulo em 2023.", f"{i}.pdf") for i in range(10)]
    retriever = GraphRetriever(SimpleNamespace(property_graph_store=store_for(nodes)), None, use_llm=False)
    assert len(retriever.retrieve_entity_context([NodeWithScore(node=nodes[0])], "Indústria em 2023")) == 2


def test_entity_expansion_follows_audited_relation():
    first, other = node("first", "Tema inicial."), node("other", "Tema relacionado.", "outro.pdf")
    store = SimplePropertyGraphStore()
    store.upsert_llama_nodes([first, other])
    a, b = EntityNode(name="A", label="Setor"), EntityNode(name="B", label="Indicador")
    store.upsert_nodes([a, b])
    store.upsert_relations([
        Relation(label="HAS_ENTITY", source_id="first", target_id=a.id),
        Relation(label="HAS_ENTITY", source_id="other", target_id=b.id),
        Relation(label="ASSOCIADO_A", source_id=a.id, target_id=b.id,
                 properties={"source_node_id": "first", "evidence": "Menção literal."})])
    retriever = GraphRetriever(SimpleNamespace(property_graph_store=store), None, use_llm=False)
    results = retriever.retrieve_entity_context([NodeWithScore(node=first)], "tema")
    assert [item.node_id for item in results] == ["other"]
    assert "ASSOCIADO_A" in {edge["relation"] for edge in json.loads(results[0].metadata["graph_paths"])}


def test_processing_indexes_children_and_restores_literal_parent():
    text = "INDÚSTRIA\n\n" + "Uma explicação da atividade industrial paulista. " * 35
    documents = [Document(text=text, metadata={"type": "text", "source_file": "boletim.pdf", "page": 3})]
    children = process_documents(documents)
    assert len(children) > 2
    assert all(child.metadata["parent_text"] for child in children)
    assert all("parent_text" not in child.get_metadata_str(MetadataMode.EMBED) for child in children)
    assert all("parent_text" not in child.get_metadata_str(MetadataMode.LLM) for child in children)
    ranked = [NodeWithScore(node=child, score=0.8) for child in children]
    parents = expand_parents(ranked)
    assert len(parents) < len(children)
    assert len({parent.node_id for parent in parents}) == len(parents)
    assert all(parent.text in text for parent in parents)
    assert all(parent.metadata["source_file"] == "boletim.pdf" and parent.metadata["page"] == 3 for parent in parents)
    assert {identity for parent in parents for identity in parent.metadata["parent_child_ids"]} == {child.node_id for child in children}


def test_parent_identity_does_not_merge_different_sources():
    documents = [Document(text="Mesmo texto.", metadata={"source_file": source, "page": 1})
                 for source in ("a.pdf", "b.pdf")]
    parents, texts = prepare_parents(documents)
    assert len(texts) == 2
    assert parents[0].node_id != parents[1].node_id


def test_oversized_parent_falls_back_to_child():
    child = node("child", "Informação pontual.")
    child.metadata.update(parent_id="big-parent", parent_text="Contexto. " * 1000)
    results = expand_parents([NodeWithScore(node=child)])
    assert results[0].node_id == "child"


def test_parent_size_invalidates_ingestion_fingerprint(monkeypatch):
    before = _pipeline_fingerprint()
    monkeypatch.setenv("RAG_PARENT_SIZE", "800")
    assert _pipeline_fingerprint() != before


def test_community_detection_covers_orphans_and_ignores_page_adjacency():
    nodes = [node("industry", "Indústria paulista.", "a.pdf"),
             node("pib", "Produto interno bruto.", "b.pdf"),
             node("orphan", "Nota sem entidade reconhecida.", "c.pdf")]
    store = store_for(nodes)
    store.upsert_relations([Relation(label="NEXT_CHUNK", source_id="industry", target_id="pib")])
    records = detect_communities(store, nodes)
    assert set().union(*(set(record["source_ids"]) for record in records)) == {item.node_id for item in nodes}
    assert any(record["method"] == "document_fallback" and record["source_ids"] == ["orphan"] for record in records)
    assert not any({"industry", "pib"} <= set(record["source_ids"]) for record in records)
    assert records == detect_communities(store, nodes)


def fake_llm():
    return SimpleNamespace(model="fake", complete=Mock(return_value=SimpleNamespace(text="Síntese candidata com fontes.")))


def test_global_search_uses_every_community_and_reuses_cache(tmp_path):
    nodes = [node("a", "Indústria paulista.", "a.pdf"), node("b", "Nota complementar sem entidade.", "b.pdf")]
    store, llm = store_for(nodes), fake_llm()
    search = CommunitySearch(store, nodes, llm, tmp_path / "communities.json")
    result = search.answer("Quais temas aparecem nos boletins?")
    assert {item.node_id for item in result.nodes} == {"a", "b"}
    assert result.knowledge["global_search"]["all_communities_processed"]
    for community in search.communities:
        assert community["id"] in llm.complete.call_args.args[0]
    cached = CommunitySearch(store, nodes, fake_llm(), search.cache_path)
    cached.summaries()
    cached.llm.complete.assert_not_called()


def test_summary_cache_invalidates_after_source_or_model_change(tmp_path):
    nodes = [node("a", "Indústria paulista.")]
    store = store_for(nodes)
    original = CommunitySearch(store, nodes, fake_llm(), tmp_path / "cache.json")
    original.summaries()
    nodes[0].text += " Informação nova."
    changed = CommunitySearch(store, nodes, fake_llm(), original.cache_path)
    assert changed.fingerprint != original.fingerprint
    changed.summaries()
    assert changed.llm.complete.called
    different_llm = fake_llm()
    different_llm.model = "outro"
    assert CommunitySearch(store, nodes, different_llm, original.cache_path).fingerprint != changed.fingerprint


def test_failed_summarization_keeps_previous_cache(tmp_path):
    nodes = [node("a", "Indústria paulista.")]
    store = store_for(nodes)
    original = CommunitySearch(store, nodes, fake_llm(), tmp_path / "cache.json")
    original.summaries()
    previous = original.cache_path.read_bytes()
    llm = fake_llm()
    llm.model = "new"
    llm.complete.side_effect = RuntimeError("Falha de API")
    changed = CommunitySearch(store, nodes, llm, original.cache_path)
    with pytest.raises(RuntimeError):
        changed.summaries()
    assert original.cache_path.read_bytes() == previous


def test_large_source_is_processed_without_truncation(tmp_path):
    text = "Começo. " + "Conteúdo intermediário. " * 600 + "FINAL_IMPORTANTE"
    nodes = [node("a", text)]
    search = CommunitySearch(store_for(nodes), nodes, fake_llm(), tmp_path / "cache.json")
    search.summaries()
    prompts = [call.args[0] for call in search.llm.complete.call_args_list]
    assert any("FINAL_IMPORTANTE" in prompt for prompt in prompts)
    assert all(len(prompt) <= 4000 for prompt in prompts)
    assert sum(prompt.count("Conteúdo intermediário.") for prompt in prompts) >= 590


def test_global_routing_skips_local_retrievers(tmp_path):
    nodes = [node("a", "Indústria paulista.")]
    search = CommunitySearch(store_for(nodes), nodes, fake_llm(), tmp_path / "cache.json")
    local = Mock()
    engine = AnalysisEngine(local, local, local, fake_llm(), global_search=search)
    result = asyncio.run(engine.answer("Quais temas aparecem nos boletins?", ["global"], "temas"))
    assert result.knowledge["global_search"]["communities"] >= 1
    local.retrieve.assert_not_called()
    assert interpret_query("Quais temas aparecem nos boletins?", None)["sources"] == ["text", "graph", "global"]


def test_global_disabled_and_local_questions_are_not_routed(monkeypatch):
    assert not is_global_question("Qual foi o PIB paulista em 2023?")
    monkeypatch.setenv("RAG_GLOBAL_SEARCH", "0")
    llm = SimpleNamespace(complete=lambda _: SimpleNamespace(text='{"sources": ["global", "text"]}'))
    result = interpret_query("Quais temas aparecem nos boletins?", llm)
    assert "global" not in result["sources"]


def test_empty_and_oversized_summaries_do_not_create_cache(tmp_path):
    nodes = [node("a", "Indústria paulista.")]
    for text in ("", "X" * 201):
        llm = SimpleNamespace(complete=lambda _: SimpleNamespace(text=text))
        search = CommunitySearch(store_for(nodes), nodes, llm, tmp_path / "cache.json")
        from rag_app.model_output import EmptyModelResponse
        with pytest.raises(EmptyModelResponse if not text else ValueError):
            search.summaries()
        assert not search.cache_path.exists()


def test_cancelled_global_request_stops_before_next_llm_call(tmp_path):
    nodes = [node("a", "Indústria paulista."), node("b", "Nota sem entidade.", "outra.pdf")]
    cancellation = threading.Event()
    llm = fake_llm()
    def complete(_prompt):
        cancellation.set()
        return SimpleNamespace(text="Síntese parcial.")
    llm.complete.side_effect = complete
    search = CommunitySearch(store_for(nodes), nodes, llm, tmp_path / "cache.json")
    with pytest.raises(RuntimeError, match="cancelada"):
        search.answer("Quais temas aparecem nos boletins?", cancellation)
    assert llm.complete.call_count == 1
    assert not search.cache_path.exists()


def test_parent_and_entity_expansion_reach_normal_synthesis():
    seed = node("a", "Indústria paulista em 2023.", "a.pdf")
    seed.metadata.update(parent_id="parent:a", parent_text=seed.text + " Ressalva da fonte: dados preliminares.")
    related = node("b", "Indústria paulista em 2023: contexto complementar.", "b.pdf")
    graph = GraphRetriever(SimpleNamespace(property_graph_store=store_for([seed, related])), None, use_llm=False)
    text = SimpleNamespace(retrieve=lambda _: [NodeWithScore(node=seed, score=0.9)])
    unused = SimpleNamespace(retrieve=lambda _: [])
    llm = fake_llm()
    engine = AnalysisEngine(text, unused, unused, llm, graph_retriever=graph,
                            knowledge_nodes=[seed, related])
    result = asyncio.run(engine.answer("O que dizem as fontes sobre a indústria paulista em 2023?",
                                      ["text"], "Indústria paulista em 2023"))
    assert {item.node_id for item in result.nodes} == {"parent:a", "b"}
    assert "dados preliminares" in llm.complete.call_args.args[0]
    assert "contexto complementar" in llm.complete.call_args.args[0]
    assert any(path["node_id"] == "b" for path in result.retrieval_paths)


def test_global_http_contract_keeps_literal_sources_and_diagnostics(tmp_path):
    from query_service import execute_engine_query
    nodes = [node("a", "Indústria paulista.", "boletim.pdf")]
    search = CommunitySearch(store_for(nodes), nodes, fake_llm(), tmp_path / "cache.json")
    unused = SimpleNamespace(retrieve=lambda _: [])
    engine = AnalysisEngine(unused, unused, unused, fake_llm(), global_search=search)
    response, diagnostics = asyncio.run(execute_engine_query(
        question="Quais temas aparecem nos boletins?", engine=engine, interp_llm=None,
        interpreter=interpret_query, rag_type="graph", rag_label="GraphRAG"))
    assert "global" in response.sources_used
    assert response.sources[0].file == "boletim.pdf"
    assert response.sources[0].excerpt == "Indústria paulista."
    assert response.knowledge["global_search"]["all_communities_processed"]
    assert diagnostics.chunks == 1


def test_cache_replace_failure_preserves_temporary(tmp_path, monkeypatch):
    nodes = [node("a", "Indústria paulista.")]
    search = CommunitySearch(store_for(nodes), nodes, fake_llm(), tmp_path / "cache.json")
    search.cache_path.write_text("previous", encoding="utf-8")
    def fail_replace(*args):
        raise PermissionError("arquivo aberto")
    monkeypatch.setattr("community_search.os.replace", fail_replace)
    with pytest.raises(PermissionError):
        search.summaries()
    assert search.cache_path.read_text(encoding="utf-8") == "previous"
    assert len(list(tmp_path.glob("*.tmp"))) == 1
    assert search._summaries is None
