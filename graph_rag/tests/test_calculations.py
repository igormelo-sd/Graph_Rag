"""Casos preparados para execução posterior; não executados nesta alteração."""
import json
from types import SimpleNamespace

import pandas as pd

from calculations import calculate


def _llm(operation, refs):
    return SimpleNamespace(complete=lambda _: SimpleNamespace(text=json.dumps({"operation": operation, "operands": refs})))


def test_variacao_calculada_preserva_operandos_e_fontes():
    column = "Estoque de emprego (mil pessoas)"
    frame = pd.DataFrame({"Ano": [2020, 2021], "Território": ["Estado de São Paulo"] * 2, column: [100, 120]})
    nodes = [SimpleNamespace(node_id=f"original-{year}", metadata={"source_file": "fonte.pdf", "page": 1},
                             get_content=lambda year=year, value=value: f"Estoque de emprego no Estado de São Paulo: {value} mil pessoas em {year}.")
             for year, value in [(2020, 100), (2021, 120)]]
    _, traces = calculate("Qual a variação?", frame, None,
                          _llm("percent_change", [{"row": 0, "column": column}, {"row": 1, "column": column}]), nodes)
    assert traces[0]["result"] == "20,00 %"
    assert traces[0]["arithmetic_verified"]
    assert traces[0]["semantic_status"] == "requires_review"
    assert traces[0]["operands"][0]["sources"][0]["node_id"] == "original-2020"


def test_operando_ausente_na_fonte_impede_calculo():
    column = "Emprego (mil pessoas)"
    frame = pd.DataFrame({"Ano": [2020, 2021], column: [100, 999]})
    node = SimpleNamespace(get_content=lambda: "100 mil pessoas", metadata={})
    _, traces = calculate("Qual a diferença?", frame, None,
                          _llm("difference", [{"row": 0, "column": column}, {"row": 1, "column": column}]), [node])
    assert traces == []


def test_operacao_fora_da_lista_nao_e_executada():
    frame = pd.DataFrame({"Valor": [1, 2]})
    _, traces = calculate("Calcule", frame, None, _llm("exec", []), [])
    assert traces == []


def test_comparacao_de_colunas_anuais_usa_cabecalhos_originais(monkeypatch):
    from document_context import structure_payload
    from llama_index.core.schema import TextNode, NodeWithScore
    monkeypatch.setenv("RAG_ONTOLOGY_ENABLE", "1")
    columns = ["Indicador", "2022", "2023"]
    rows = [["Estoque de emprego (mil pessoas)", "100", "120"]]
    frame = pd.DataFrame(rows, columns=columns)
    text = "Indicador: Estoque de emprego (mil pessoas)\n2022: 100\n2023: 120\nFonte: fonte.pdf"
    metadata = {"type": "table", "source_file": "fonte.pdf", "page": 1, "table_key": "table-a"}
    metadata["table_structure"] = structure_payload(columns, rows, metadata, "Estado de São Paulo")
    node = TextNode(id_="table-chunk", text=text, metadata=metadata, excluded_llm_metadata_keys=["table_structure"], excluded_embed_metadata_keys=["table_structure"])
    _, traces = calculate("Qual a variação do estoque de emprego no Estado de São Paulo de 2022 para 2023?", frame, None,
                          _llm("percent_change", [{"row": 0, "column": "2022"}, {"row": 0, "column": "2023"}]), [NodeWithScore(node=node, score=0.8)])
    assert traces[0]["result"] == "20,00 %"
    assert traces[0]["operands"][0]["dimensions"]["period"] == ["2022"]
    assert traces[0]["operands"][1]["dimensions"]["period"] == ["2023"]
    assert traces[0]["operands"][0]["observation_candidates"]


def test_plano_nao_pode_trocar_estado_por_municipio():
    column = "Estoque de emprego (mil pessoas)"
    frame = pd.DataFrame({"Ano": [2022, 2023], "Território": ["Município de São Paulo"] * 2, column: [100, 120]})
    nodes = [SimpleNamespace(node_id=str(year), metadata={"source_file": "fonte.pdf", "page": 1},
                             get_content=lambda year=year, value=value: f"Estoque de emprego no Município de São Paulo: {value} mil pessoas em {year}.")
             for year, value in [(2022, 100), (2023, 120)]]
    _, traces = calculate("Variação do emprego no Estado de São Paulo", frame, None,
                          _llm("percent_change", [{"row": 0, "column": column}, {"row": 1, "column": column}]), nodes)
    assert traces == []
