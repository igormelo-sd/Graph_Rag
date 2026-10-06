"""Regressões preparadas; execução depende de autorização posterior."""
import json
from types import SimpleNamespace

from llama_index.core.schema import TextNode, NodeWithScore

from rag_selection import fuse, literal_table_payload, pack_context, select_coverage, sufficiency


def node(identity, text, **metadata):
    return NodeWithScore(node=TextNode(id_=identity, text=text,
        metadata={"type": "text", "source_file": "fonte.pdf", "page": 1, **metadata}))


def test_fusao_premia_consenso_sem_comparar_scores(monkeypatch):
    monkeypatch.setenv("RAG_ONTOLOGY_ENABLE", "0")
    a, b, c = node("a", "A"), node("b", "B"), node("c", "C")
    a.score, b.score = 1000, 0.01
    assert fuse([[a, b], [c, b]], "consulta")[0].node_id == "b"


def test_repeticao_na_lista_nao_ganha_votos(monkeypatch):
    monkeypatch.setenv("RAG_ONTOLOGY_ENABLE", "0")
    a, b = node("a", "A"), node("b", "B")
    assert fuse([[a, a, a, b], [b]], "consulta")[0].node_id == "b"


def test_orcamento_omite_bloco_grande_sem_cortar_outro(monkeypatch):
    monkeypatch.setenv("RAG_MAX_CONTEXT_TOKENS", "1000")
    large, small = node("large", "X" * 5000), node("small", "Trecho completo.")
    context, included = pack_context([large, small], "consulta")
    assert "Trecho completo." in context and "XXXXX" not in context
    assert [n.node_id for n in included] == ["small"]


def test_cobertura_reserva_segundo_periodo(monkeypatch):
    monkeypatch.setenv("RAG_ONTOLOGY_ENABLE", "1")
    base = node("base", "PIB no Estado de São Paulo: 100 bilhões de reais em 2022.")
    repeated = node("repeat", "PIB no Estado de São Paulo: 100 bilhões de reais em 2022.")
    final = node("final", "PIB no Estado de São Paulo: 110 bilhões de reais em 2023.")
    question = "PIB no Estado de São Paulo em 2022 e 2023"
    assert {n.node_id for n in select_coverage([base, repeated, final], question, 2)} == {"base", "final"}
    assert sufficiency(question, [base])["missing"]["period"] == ["2023"]


def test_uniao_de_recortes_desconectados_nao_prova_cobertura(monkeypatch):
    monkeypatch.setenv("RAG_ONTOLOGY_ENABLE", "1")
    a = node("a", "PIB no Estado de São Paulo: 100 bilhões de reais em 2022.")
    b = node("b", "PIB no Município de São Paulo: 20 bilhões de reais em 2023.")
    report = sufficiency("PIB no Estado de São Paulo em 2023", [a, b])
    assert report["status"] == "partial" and not report["semantic_verified"]


def test_celulas_literais_preservam_virgula_e_deduplicam_linha():
    table = {"columns": ["Ano", "Taxa (%)"], "rows": [["2023", "7,9"]], "row_indices": [4], "table_id": "t"}
    a = node("a", "Tabela", type="table", table_structure=json.dumps(table))
    b = node("b", "Tabela", type="table", table_structure=json.dumps(table))
    assert literal_table_payload([a, b])["rows"] == [["2023", "7,9"]]


def test_esquemas_incompativeis_nao_sao_combinados():
    a = node("a", "Tabela", table_structure=json.dumps({"columns": ["Ano", "PIB"], "rows": [["2023", "10"]]}))
    b = node("b", "Tabela", table_structure=json.dumps({"columns": ["Ano", "Emprego"], "rows": [["2023", "10"]]}))
    assert literal_table_payload([a, b]) is None


def test_notas_acompanham_fonte_do_resultado_estruturado(monkeypatch):
    monkeypatch.setenv("RAG_MAX_CONTEXT_TOKENS", "1000")
    table = {"columns": ["PIB"], "rows": [["10"]], "title": "PIB", "notes": ["Valores nominais."]}
    a = node("a", "PIB: 10", table_structure=json.dumps(table))
    context, included = pack_context([a], "consulta", [("Resultado literal", [a])])
    assert "Valores nominais." in context
    assert [n.node_id for n in included] == ["a"]


def test_alternativa_com_periodo_alterado_e_rejeitada(monkeypatch):
    from text_retriever import ProtectedFusionRetriever
    monkeypatch.setenv("RAG_ONTOLOGY_ENABLE", "1")
    monkeypatch.setenv("RAG_DEEP_SEARCH", "0")
    monkeypatch.setenv("RAG_QUERY_FUSION_QUERIES", "2")
    calls = []
    retriever = SimpleNamespace(retrieve=lambda query: calls.append(query) or [])
    llm = SimpleNamespace(complete=lambda prompt: SimpleNamespace(text="PIB no Estado de São Paulo em 2022"))
    question = "PIB no Estado de São Paulo em 2023"
    ProtectedFusionRetriever(retriever, llm).retrieve(question)
    assert calls == [question]


def test_sobreposicao_nao_elimina_evidencia_de_outra_fonte(monkeypatch):
    monkeypatch.setenv("RAG_ONTOLOGY_ENABLE", "0")
    text = "Uma explicação documental suficientemente longa para representar um parágrafo completo. " * 2
    a = node("a", text + " Ressalva adicional.")
    b = node("b", text)
    c = node("c", text, source_file="outra.pdf")
    assert [n.node_id for n in fuse([[a, b, c]], "consulta")] == ["a", "c"]
