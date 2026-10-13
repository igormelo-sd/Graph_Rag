"""Contratos semânticos preparados; não executados durante a implementação."""
import json
from types import SimpleNamespace

import pytest

from document_context import structure_payload, context_links
from domain_ontology import extract_observations, facets, node_observations
from knowledge_analytics import CorpusKnowledge, clarification_request, comparison_graph, divergence_candidates, hierarchy_scope
from relation_semantics import relation_attributes


@pytest.fixture(autouse=True)
def ontology_active(monkeypatch):
    monkeypatch.setenv("RAG_ONTOLOGY_ENABLE", "1")


def table_node(columns, rows, title="", notes=()):
    text = "\n---\n".join("\n".join(f"{header}: {value}" for header, value in zip(columns, row)) + "\nFonte: tabela.pdf" for row in rows)
    metadata = {"type": "table", "source_file": "tabela.pdf", "page": 3, "table_key": "table-a"}
    metadata["table_structure"] = structure_payload(columns, rows, metadata, title, notes)
    return SimpleNamespace(node_id="chunk-a", text=text, metadata=metadata, get_content=lambda: text)


def observation(value="7,9%", period="2023", region="Estado de São Paulo", source="Seade", node_id="a"):
    text = f"Taxa de desocupação no {region}: {value} em {period}, segundo {source}."
    return extract_observations(text, {"source_file": node_id + ".pdf", "page": 1}, node_id)[0]


def test_cabecalho_anual_liga_cada_valor_ao_seu_ano():
    node = table_node(["Indicador", "2022", "2023"], [["Taxa de desocupação (%)", "8,2", "7,9"]], "Estado de São Paulo")
    records = node_observations(node)
    assert [record["dimensions"]["period"] for record in records] == [["2022"], ["2023"]]
    assert [record["value"] for record in records] == ["8,2", "7,9"]
    assert all(record["dimensions"]["unit"] == ["percentual"] for record in records)
    assert all(node.text[record["provenance"]["start"]:record["provenance"]["end"]] == record["value"] for record in records)


def test_linhas_com_indicadores_diferentes_nao_contaminam_outras_celulas():
    node = table_node(["Indicador", "2023"], [["Taxa de desocupação (%)", "7,9"], ["Participação (%)", "62,0"]], "Estado de São Paulo")
    records = node_observations(node)
    assert records[0]["dimensions"]["indicator"] == ["desocupacao"]
    assert records[1]["dimensions"]["indicator"] == ["participacao"]


def test_notas_preservam_cobertura_sem_confundir_publicacao():
    node = table_node(["Ano", "Estoque de emprego (mil pessoas)"], [["2023", "100"]], "Estado de São Paulo",
                      ["Nota: somente vínculos formais.", "Publicação: 2024", "Fonte: Caged"])
    record = node_observations(node)[0]
    assert record["dimensions"]["period"] == ["2023"]
    assert record["publication_periods"] == ["2024"]
    assert record["dimensions"]["source"] == ["caged"]
    assert record["dimensions"]["coverage"] == ["formal"]
    assert record["provenance"]["notes"][0] == "Nota: somente vínculos formais."


def test_publicacao_em_coluna_nao_vira_periodo_estatistico():
    node = table_node(["Ano", "Publicação", "Taxa de desocupação (%)"], [["2023", "2024", "7,9"]], "Estado de São Paulo")
    record = node_observations(node)[0]
    assert record["dimensions"]["period"] == ["2023"]
    assert record["publication_periods"] == ["2024"]


def test_tabela_sem_unidade_nao_recebe_unidade_inventada():
    node = table_node(["Indicador", "2023"], [["PIB", "100"]], "Estado de São Paulo")
    record = node_observations(node)[0]
    assert record["status"] == "requires_review"
    assert record["dimensions"]["unit"] == []


def test_vinculo_documental_exige_literal_e_mesma_pagina():
    table = table_node(["Indicador", "2023"], [["PIB", "100"]])
    table.metadata.update(table_title="Tabela 1 — PIB", table_notes=json.dumps(["Nota: valores nominais."]))
    note = SimpleNamespace(node_id="nota", text="Nota: valores nominais.", metadata={"type": "text", "source_file": "tabela.pdf", "page": 3})
    other_page = SimpleNamespace(node_id="outra", text=note.text, metadata={**note.metadata, "page": 4})
    links = list(context_links([table, note, other_page]))
    assert [(target.node_id, relation) for _, target, relation, _ in links] == [("nota", "TEM_NOTA")]


def test_divergencias_incluem_fontes_distintas_e_exigem_revisao():
    records = [observation("7,9%", source="Seade", node_id="a"), observation("8,2%", source="IBGE", node_id="b")]
    conflicts = divergence_candidates(records)
    assert len(conflicts) == 1
    assert conflicts[0]["status"] == "requires_review"
    assert len(conflicts[0]["alternatives"]) == 2


def test_mesmo_valor_com_casas_decimais_distintas_nao_e_divergencia():
    assert divergence_candidates([observation("7,9%"), observation("7,90%", node_id="b")]) == []


def test_escalas_diferentes_nao_geram_falsa_divergencia():
    first, second = observation("7,9%"), observation("8,2%", node_id="b")
    first["dimensions"]["scale"], second["dimensions"]["scale"] = ["mil"], ["milhao"]
    assert divergence_candidates([first, second]) == []


def test_ambiguidade_pede_esclarecimento_sem_inventar_estado():
    request = clarification_request("Qual o PIB de São Paulo em 2023?", {"estado_sp"})
    assert request["required"] and request["dimension"] == "region"
    assert request["options"][0]["has_indexed_observations"]
    assert clarification_request("Qual o PIB do Município de São Paulo em 2023?") is None


def test_hierarquia_seleciona_municipios_sem_agregar_valores():
    scope = hierarchy_scope("Quais municípios do Estado de São Paulo têm PIB em 2023?")
    assert scope["region"] == {"municipio_sp"}
    assert "estado_sp" not in scope["region"]
    assert hierarchy_scope("Quais subsetores da indústria têm emprego?")["sector"] == {"industria_transformacao", "industria_extrativa"}


def test_cobertura_registra_combinacao_ausente_sem_afirmar_inexistencia():
    node = table_node(["Indicador", "2023"], [["Taxa de desocupação (%)", "7,9"]], "Estado de São Paulo")
    report = CorpusKnowledge([node]).report("Taxa de desocupação no Estado de São Paulo em 2023 e 2024")
    assert report["matched_candidates"] == 1
    assert report["missing_requested_combinations"] == [{"indicator": "desocupacao", "region": "estado_sp", "period": "2024"}]
    assert report["available_combinations"][0]["period"] == "2023"
    assert report["automatic_aggregation"] is False


def test_grafo_de_calculo_preserva_base_final_formula_e_fontes():
    first, second = observation(period="2022"), observation("8,2%", node_id="b")
    trace = {"operation": "percentage_points", "formula": "8,2 - 7,9", "result": "0,30 p.p.", "arithmetic_verified": True,
             "operands": [{"value": "7.9", "observation_candidates": [first["id"]], "sources": [{"node_id": "a"}]},
                          {"value": "8.2", "observation_candidates": [second["id"]], "sources": [{"node_id": "b"}]}]}
    graph = comparison_graph([trace], [first, second])
    assert {edge["relation"] for edge in graph["relations"]} >= {"BASE_DE", "FINAL_DE", "BASEADO_EM", "SUSTENTADA_POR"}
    assert graph["persisted_as_fact"] is False


def test_negacao_nao_vira_relacao_positiva():
    with pytest.raises(ValueError, match="Negação"):
        relation_attributes("CRESCEU_EM", "O emprego não cresceu em 2023.", {}, "a")


def test_correlacao_nao_vira_causalidade():
    with pytest.raises(ValueError, match="Causalidade"):
        relation_attributes("CAUSA", "Há correlação entre o PIB e o emprego em 2023.", {}, "a")


def test_hipotese_mantem_modalidade_e_proveniencia():
    attributes = relation_attributes("CAUSA", "O PIB pode provocar crescimento do emprego em 2023.", {"source_file": "fonte.pdf", "page": 2}, "a")
    assert attributes["modality"] == "uncertain"
    assert attributes["review_status"] == "pending"
    assert json.loads(attributes["validity_periods_json"]) == ["2023"]
    assert attributes["source_node_id"] == "a"


def test_interpretador_pede_esclarecimento_sem_chamar_llm():
    from query_interpreter import interpret_query
    def forbidden(_):
        raise AssertionError("Não deve chamar o LLM antes do esclarecimento")
    result = interpret_query("Qual o PIB de São Paulo em 2023?", SimpleNamespace(complete=forbidden))
    assert result["sources"] == [] and result["clarification"]["required"]


def test_espacos_na_celula_preservam_offsets_do_valor():
    node = table_node(["Indicador", "2023"], [["Taxa de desocupação (%)", " 7,9 "]], "Estado de São Paulo")
    record = node_observations(node)[0]
    assert node.text[record["provenance"]["start"]:record["provenance"]["end"]] == "7,9"


def test_resumo_gerado_nao_vira_nova_observacao_documental():
    node = SimpleNamespace(text="Taxa de desocupação no Estado de São Paulo: 7,9% em 2023.", metadata={"raptor_level": 1})
    assert node_observations(node) == []


def test_divulgacao_nao_vira_periodo_de_referencia():
    node = table_node(["Ano", "Taxa de desocupação (%)"], [["2023", "7,9"]], "Estado de São Paulo", ["Divulgação: 2024"])
    record = node_observations(node)[0]
    assert record["dimensions"]["period"] == ["2023"]
    assert record["publication_periods"] == ["2024"]


def test_sem_carteira_nao_nega_relacao_com_fonte():
    attributes = relation_attributes("MEDIDO_POR", "O emprego sem carteira é medido pela PNAD em 2023.", {}, "a")
    assert attributes["polarity"] == "affirmed"
