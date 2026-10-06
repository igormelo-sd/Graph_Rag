"""Casos de travessia e proveniência preparados para execução posterior."""
import json
from types import SimpleNamespace

from llama_index.core.graph_stores import SimplePropertyGraphStore
from llama_index.core.schema import TextNode, NodeWithScore

from graph_indexing import _inject_structural_triplets, _inject_domain_triplets
from graph_retriever import GraphRetriever


def graph(nodes):
    store = SimplePropertyGraphStore()
    _inject_structural_triplets(store, nodes)
    _inject_domain_triplets(store, nodes)
    return GraphRetriever(SimpleNamespace(property_graph_store=store), llm=None, use_llm=False)


def text_node(identity, text, page=1, chunk=1):
    return TextNode(id_=identity, text=text, metadata={"type": "text", "source_file": "fonte.pdf", "page": page, "chunk_id": chunk})


def test_tabela_traz_nota_por_arestas_e_preserva_caminho(monkeypatch):
    monkeypatch.setenv("RAG_ONTOLOGY_ENABLE", "1")
    table = TextNode(id_="table-chunk", text="PIB: 100", metadata={"type": "table", "source_file": "fonte.pdf", "page": 1,
        "table_key": "table-a", "table_title": "Tabela 1 — PIB", "table_notes": json.dumps(["Nota: valores nominais."])})
    note = text_node("note-chunk", "Nota: valores nominais.")
    unrelated = text_node("other-page", "Nota: valores nominais.", page=2)
    result = graph([table, note, unrelated]).retrieve_context([NodeWithScore(node=table, score=0.8)])
    assert [node.node_id for node in result] == ["note-chunk"]
    assert {edge["relation"] for edge in json.loads(result[0].metadata["graph_paths"])} == {"REPRESENTADA_EM", "TEM_NOTA"}


def test_consulta_com_dois_anos_recupera_observacoes_separadas(monkeypatch):
    monkeypatch.setenv("RAG_ONTOLOGY_ENABLE", "1")
    first = text_node("base", "Taxa de desocupação no Estado de São Paulo: 8,2% em 2022.")
    final = text_node("final", "Taxa de desocupação no Estado de São Paulo: 7,9% em 2023.", chunk=2)
    result = graph([first, final]).retrieve("Taxa de desocupação no Estado de São Paulo em 2022 e 2023")
    assert {node.node_id for node in result} == {"base", "final"}


def test_hierarquia_municipal_nao_troca_valor_do_estado_pelo_municipio(monkeypatch):
    monkeypatch.setenv("RAG_ONTOLOGY_ENABLE", "1")
    state = text_node("state", "PIB no Estado de São Paulo: 100 bilhões de reais em 2023.")
    city = text_node("city", "PIB no Município de São Paulo: 20 bilhões de reais em 2023.", chunk=2)
    result = graph([state, city]).retrieve("Quais municípios do Estado de São Paulo têm PIB em 2023?")
    assert {node.node_id for node in result} == {"city"}


def test_orcamento_de_contexto_e_deduplicacao(monkeypatch):
    monkeypatch.setenv("RAG_ONTOLOGY_ENABLE", "1")
    nodes = [text_node(str(i), f"Contexto narrativo {i}.", chunk=i) for i in range(1, 5)]
    result = graph(nodes).retrieve_context([NodeWithScore(node=nodes[1], score=0.8)], max_nodes=1)
    assert len(result) == 1
    assert result[0].node_id != nodes[1].node_id


def test_relacoes_auditadas_sao_consultadas_localmente_por_alias(monkeypatch):
    from llama_index.core.graph_stores.types import EntityNode, Relation
    from relation_semantics import relation_attributes
    monkeypatch.setenv("RAG_ONTOLOGY_ENABLE", "1")
    chunk = text_node("relation-source", "Há correlação entre o PIB e o emprego em 2023.")
    store = SimplePropertyGraphStore()
    store.upsert_llama_nodes([chunk])
    first = EntityNode(name="Indicador:Produto interno bruto", label="Indicador")
    second = EntityNode(name="Indicador:Emprego", label="Indicador")
    store.upsert_nodes([first, second])
    store.upsert_relations([Relation(label="ASSOCIADO_A", source_id=first.id, target_id=second.id,
        properties=relation_attributes("ASSOCIADO_A", chunk.text, chunk.metadata, chunk.node_id))])
    retriever = GraphRetriever(SimpleNamespace(property_graph_store=store), llm=None, use_llm=False)
    result = retriever.retrieve("Qual a relação entre PIB e emprego em 2023?")
    assert [node.node_id for node in result] == ["relation-source"]
    paths = json.loads(result[0].metadata["graph_paths"])
    assert paths[0]["relation"] == "ASSOCIADO_A"
    assert paths[0]["modality"] == "asserted"
