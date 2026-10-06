"""Regressões de significado e proveniência; preparadas, não executadas."""
from types import SimpleNamespace
import json

from domain_ontology import (territories, periods, validate_relation, extract_observations,
                             filter_candidates, facets, comparison_issues, preserve_query, approved_extensions)


def test_estado_municipio_e_ambiguidade_sao_distintos():
    assert territories("Estado de São Paulo")[0] == {"estado_sp"}
    assert territories("Município de São Paulo")[0] == {"municipio_sp"}
    values, issues = territories("São Paulo")
    assert not values and issues
    assert territories("Região Metropolitana de São Paulo")[0] == {"rmsp"}


def test_periodos_preservam_granularidade():
    assert periods("1T2023") == {"2023-Q1"}
    assert periods("janeiro de 2023") == {"2023-01"}
    assert periods("2023") == {"2023"}


def test_relacao_de_observacao_nao_aceita_indicador_como_sujeito():
    assert validate_relation("ObservacaoEstatistica", "APLICA_SE_A", "Estado")
    assert not validate_relation("Indicador", "APLICA_SE_A", "Estado")
    assert not validate_relation("ObservacaoEstatistica", "RELACAO_INVENTADA", "Estado")


def test_observacao_preserva_ocorrencia_e_ignora_ano():
    text = "Taxa de desocupação no Estado de São Paulo: 7,9% em 2023."
    records = extract_observations(text, {"source_file": "fonte.pdf", "page": 3}, "chunk-a")
    assert len(records) == 1
    assert records[0]["value"] == "7,9%"
    assert records[0]["dimensions"]["region"] == ["estado_sp"]
    origin = records[0]["provenance"]
    assert text[origin["start"]:origin["end"]].strip() == "7,9%"
    assert origin["node_id"] == "chunk-a"


def test_dimensao_ausente_nao_e_completada():
    records = extract_observations("Taxa de desocupação: 7,9%.", {}, "a")
    assert records[0]["status"] == "requires_review"
    assert records[0]["dimensions"]["region"] == []


def test_busca_exclui_conflito_mantem_contexto_incompleto():
    nodes = [SimpleNamespace(text=text) for text in ["PIB do Município de São Paulo em 2023", "PIB do Estado de São Paulo em 2023", "Contexto do PIB"]]
    result = filter_candidates(nodes, "PIB do Estado de São Paulo em 2023")
    assert result == nodes[1:]


def test_reescrita_nao_resolve_territorio_ambiguo():
    original = "Qual o PIB de São Paulo em 2023?"
    assert preserve_query(original, "PIB do Estado de São Paulo em 2023") == original


def test_comparacao_rejeita_escalas_diferentes():
    base = facets("Estoque de emprego no Estado de São Paulo em 2022: 100 mil pessoas")
    final = facets("Estoque de emprego no Estado de São Paulo em 2023: 100 milhões de pessoas")
    assert "scale: incompatível" in comparison_issues([base, final], "difference")


def test_extensao_nao_revisada_nao_entra_no_modelo(tmp_path, monkeypatch):
    path = tmp_path / "extensions.json"
    path.write_text(json.dumps({"entity_types": [{"name": "Empresa", "description": "Organização", "parent": "FonteDados", "reviewed": False}]}), encoding="utf-8")
    monkeypatch.setenv("RAG_ONTOLOGY_EXTENSIONS", str(path))
    assert approved_extensions() == {}


def test_hierarquia_nao_mistura_setor_e_territorio():
    assert validate_relation("Municipio", "PARTE_DE", "Estado")
    assert not validate_relation("Setor", "PARTE_DE", "Estado")


def test_comparacao_nao_mistura_ano_e_trimestre():
    base = facets("Estoque de emprego no Estado de São Paulo em 2022: 100 pessoas")
    final = facets("Estoque de emprego no Estado de São Paulo em 1T2023: 120 pessoas")
    assert "period: repetido ou granularidade diferente" in comparison_issues([base, final], "difference")


def test_nao_soma_estoques_de_periodos_diferentes():
    base = facets("Estoque de emprego no Estado de São Paulo em 2022: 100 pessoas")
    final = facets("Estoque de emprego no Estado de São Paulo em 2023: 120 pessoas")
    assert any(issue.startswith("sum:") for issue in comparison_issues([base, final], "sum"))


def test_numero_do_trimestre_nao_vira_observacao():
    records = extract_observations("Taxa de desocupação no Estado de São Paulo no 1 trimestre de 2023: 7,9%.")
    assert [record["value"] for record in records] == ["7,9%"]


def test_desemprego_nao_e_confundido_com_emprego():
    assert facets("Taxa de desemprego")["indicator"] == {"desocupacao"}


def test_mes_e_trimestre_nao_sao_comparaveis_mesmo_com_ids_de_mesmo_tamanho():
    base = facets("Estoque de emprego no Estado de São Paulo em janeiro de 2023: 100 pessoas")
    final = facets("Estoque de emprego no Estado de São Paulo em 2T2023: 120 pessoas")
    assert "period: repetido ou granularidade diferente" in comparison_issues([base, final], "difference")


def test_datas_e_meses_abreviados_preservam_granularidade():
    assert periods("jan./2023") == {"2023-01"}
    assert periods("01/2023") == {"2023-01"}
    assert periods("31/01/2023") == {"2023-01-31"}
    assert periods("2023-01-31") == {"2023-01-31"}
    assert periods("2023-01") == {"2023-01"}


def test_partes_da_data_nao_viram_valores_observados():
    records = extract_observations("PIB do Estado de São Paulo em 31/01/2023: 100 bilhões de reais.")
    assert [record["value"] for record in records] == ["100"]
    assert records[0]["dimensions"]["period"] == ["2023-01-31"]
