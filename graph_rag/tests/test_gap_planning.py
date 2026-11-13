"""Expansão guiada pelos recortes da pergunta que o contexto ainda não sustenta."""
import json
from types import SimpleNamespace

from llama_index.core.graph_stores import SimplePropertyGraphStore
from llama_index.core.schema import TextNode

from graph_indexing import _inject_structural_triplets, _inject_domain_triplets
from graph_retriever import GraphRetriever


def graph(nodes):
    store = SimplePropertyGraphStore()
    _inject_structural_triplets(store, nodes)
    _inject_domain_triplets(store, nodes)
    return GraphRetriever(SimpleNamespace(property_graph_store=store), llm=None, use_llm=False)


def text_node(identity, text, chunk=1):
    return TextNode(id_=identity, text=text, metadata={"type": "text", "source_file": "fonte.pdf", "page": 1, "chunk_id": chunk})


def period_of(retriever, chunk_id):
    for value, observations in retriever._dimensions["period"].items():
        for observation in observations:
            if any(r.label == "SUSTENTADA_POR" and r.target_id == chunk_id for r in retriever._out(observation)):
                return value
    raise AssertionError("período não encontrado")


def test_gaps_bring_back_the_chunk_that_supports_the_missing_period(monkeypatch):
    monkeypatch.setenv("RAG_ONTOLOGY_ENABLE", "1")
    first = text_node("base", "Taxa de desocupação no Estado de São Paulo: 8,2% em 2022.")
    final = text_node("final", "Taxa de desocupação no Estado de São Paulo: 7,9% em 2023.", chunk=2)
    retriever = graph([first, final])
    question = "Taxa de desocupação no Estado de São Paulo em 2022 e 2023"
    missing = {"period": [period_of(retriever, "final")]}
    found = retriever.retrieve_gaps(question, missing, exclude_ids={"base"})
    assert [node.node_id for node in found] == ["final"]
    step = json.loads(found[0].metadata["graph_paths"])[0]
    assert step["method"] == "coverage_gap" and step["gap"].startswith("period:")
    # Trechos já escolhidos não voltam, e sem lacuna não há expansão.
    assert retriever.retrieve_gaps(question, missing, exclude_ids={"base", "final"}) == []
    assert retriever.retrieve_gaps(question, {}) == []


def test_personalized_pagerank_reaches_connected_chunks_before_unrelated_ones(monkeypatch):
    monkeypatch.setenv("RAG_ONTOLOGY_ENABLE", "1")
    table = TextNode(id_="table-chunk", text="PIB: 100", metadata={
        "type": "table", "source_file": "fonte.pdf", "page": 1, "table_key": "table-a",
        "table_title": "Tabela 1 — PIB", "table_notes": json.dumps(["Nota: valores nominais."])})
    note = text_node("note-chunk", "Nota: valores nominais.")
    other = TextNode(id_="other-doc", text="Outro assunto", metadata={"type": "text", "source_file": "outro.pdf", "page": 9,
                                                                        "chunk_id": 1})
    retriever = graph([table, note, other])
    found = retriever.retrieve_ppr([SimpleNamespace(node_id="table-chunk")], "PIB nominal", limit=5)
    ids = [node.node_id for node in found]
    assert "table-chunk" not in ids                       # a semente não volta
    assert ids.index("note-chunk") < ids.index("other-doc") if "other-doc" in ids else "note-chunk" in ids
    step = json.loads(found[0].metadata["graph_paths"])[0]
    assert step["method"] == "personalized_pagerank"
    assert retriever.retrieve_ppr([SimpleNamespace(node_id="inexistente")], "PIB") == []
