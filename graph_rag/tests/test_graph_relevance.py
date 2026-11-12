"""Seleção de vizinhos do grafo por relevância, e não pela ordem dos IDs."""
import json
from types import SimpleNamespace

import pytest
from llama_index.core.graph_stores import SimplePropertyGraphStore
from llama_index.core.schema import NodeWithScore, TextNode

from graph_indexing import _inject_domain_triplets, _inject_structural_triplets
from graph_retriever import GraphRetriever
from relation_semantics import CO_DIMENSION


@pytest.fixture(autouse=True)
def ontology(monkeypatch):
    monkeypatch.setenv("RAG_ONTOLOGY_ENABLE", "1")


def text(identity, body, source="fonte.pdf", page=1, chunk=1):
    return TextNode(id_=identity, text=body, metadata={"type": "text", "source_file": source, "page": page, "chunk_id": chunk})


def row(identity, body, table="table-a", chunk=1):
    return TextNode(id_=identity, text=body, metadata={"type": "table", "source_file": "tabelas.xlsx", "page": "Tabela 1",
                                                       "table_key": table, "chunk_id": chunk})


def retriever(nodes):
    store = SimplePropertyGraphStore()
    _inject_structural_triplets(store, nodes)
    _inject_domain_triplets(store, nodes)
    return GraphRetriever(SimpleNamespace(property_graph_store=store), None, use_llm=False), store


def test_rare_shared_entity_outranks_common_one_regardless_of_node_id():
    # "aaa" vem antes de "zzz" pela ordem dos IDs, mas só compartilha a entidade comum.
    seed = text("seed", "Desemprego e PIB no Estado de São Paulo.", "semente.pdf")
    common = [text(f"aaa{i}", "PIB no Estado de São Paulo.", f"comum{i}.pdf") for i in range(20)]
    rare = text("zzz", "Taxa de desemprego.", "raro.pdf")
    graph, _ = retriever([seed, *common, rare])
    # Pergunta sem indicador, para o filtro de recorte não descartar os trechos de PIB.
    result = graph.retrieve_entity_context([NodeWithScore(node=seed)], "Estado de São Paulo")
    assert result[0].node_id == "zzz"
    assert result[0].score > result[-1].score


def test_hub_entity_does_not_bridge_to_other_chunks(monkeypatch):
    monkeypatch.setenv("RAG_ENTITY_HUB_SHARE", "0.01")
    nodes = [text(f"n{i}", "Indústria no Estado de São Paulo.", f"{i}.pdf") for i in range(60)]
    graph, _ = retriever(nodes)
    assert graph._hub_limit() == 50
    assert graph.retrieve_entity_context([NodeWithScore(node=nodes[0])], "indústria") == []


def test_table_context_brings_note_but_not_sibling_rows():
    first = row("row-a", "Indústria 2023: 1,5")
    sibling = row("row-b", "Comércio 2023: 2,0", chunk=2)
    first.metadata.update(table_title="Tabela 1 — PIB", table_notes=json.dumps(["Nota: dados preliminares."]))
    note = text("note", "Nota: dados preliminares.", source="tabelas.xlsx", page="Tabela 1")
    graph, _ = retriever([first, sibling, note])
    found = [item.node_id for item in graph.retrieve_context([NodeWithScore(node=first)])]
    assert "note" in found and "row-b" not in found


def test_context_ties_follow_seed_order_not_node_id():
    pages = [text(f"{name}{i}", f"Trecho {name} {i}.", f"{name}.pdf", chunk=i)
             for name in ("zeta", "alfa") for i in (1, 2)]
    graph, _ = retriever(pages)
    seeds = [NodeWithScore(node=pages[0]), NodeWithScore(node=pages[2])]  # zeta1 antes de alfa1
    found = [item.node_id for item in graph.retrieve_context(seeds, max_nodes=1)]
    assert found == ["zeta2"]


def test_label_match_finds_row_with_rare_label_in_seed_table():
    title = "Tabela 3 / PIB trimestral / Estado de São Paulo / "
    rows = [row(f"r{i}", title + f"Trimestre {i}º de 2024: {i},0", chunk=i) for i in range(1, 5)]
    rows.append(row("wanted", title + "Com ajuste sazonal 1º trimestre de 2026: 1,59", chunk=9))
    graph, _ = retriever(rows)
    found = graph.label_candidates([NodeWithScore(node=rows[0])], "PIB com ajuste sazonal no 1º trimestre de 2026")
    assert found[0].node_id == "wanted"
    step = json.loads(found[0].metadata["graph_paths"])[-1]
    assert step["method"] == "row_label_match" and "sazonal" in step["evidence"]
    # O título aparece em todas as linhas e não serve, sozinho, para escolher uma.
    assert graph.label_candidates([NodeWithScore(node=rows[0])], "PIB trimestral do Estado") == []


def test_label_match_reaches_other_page_of_the_same_document():
    seed = text("seed", "Equipamentos para escritório: variação regional.", "caderno.pdf", page=51)
    summary = text("summary", "Brasil: equipamentos para escritório, dezembro 2025/dezembro 2024: 4,3", "caderno.pdf", page=29)
    other = text("other", "Livros e papelaria.", "caderno.pdf", page=30)
    elsewhere = text("elsewhere", "Brasil: equipamentos para escritório em dezembro.", "outro.pdf", page=1)
    graph, _ = retriever([seed, summary, other, elsewhere])
    found = [item.node_id for item in graph.label_candidates([NodeWithScore(node=seed)],
                                                            "Variação de equipamentos para escritório no Brasil em dezembro")]
    assert found == ["summary"]


def test_text_continues_across_consecutive_pages_of_one_document():
    end = text("end", "fim da página 4", "metodologia.pdf", page=4, chunk=3)
    start = text("start", "início da página 5", "metodologia.pdf", page=5, chunk=1)
    gap = text("gap", "página 7", "metodologia.pdf", page=7, chunk=1)
    other = text("other", "outro documento, página 5", "outro.pdf", page=5, chunk=1)
    _, store = retriever([end, start, gap, other])
    links = {(r.source_id, r.target_id) for r in store.graph.relations.values() if r.label == "NEXT_CHUNK"}
    assert links == {("end", "start")}


def test_observation_links_indicator_to_sector_without_becoming_narrated_relation():
    cell = text("cell", "Taxa de desocupação na indústria do Estado de São Paulo: 8,2% em 2023.")
    graph, store = retriever([cell])
    links = [r for r in store.graph.relations.values() if r.label == "RELACIONA_COM"]
    assert len(links) == 1
    assert links[0].properties["semantic_status"] == CO_DIMENSION
    assert links[0].properties["source_node_id"] == "cell"
    assert graph._retrieve_relations("Qual a relação entre desocupação e indústria?") == []
