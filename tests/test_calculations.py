"""Casos preparados para execução posterior; não executados nesta alteração."""
import json
from types import SimpleNamespace

import pandas as pd

from calculations import calculate


def _llm(operation, refs):
    return SimpleNamespace(complete=lambda _: SimpleNamespace(text=json.dumps({"operation": operation, "operands": refs})))


def test_variacao_calculada_preserva_operandos_e_fontes():
    column = "Emprego (mil pessoas)"
    frame = pd.DataFrame({"Ano": [2020, 2021], column: [100, 120]})
    node = SimpleNamespace(node_id="original", metadata={"source_file": "fonte.pdf", "page": 1},
                           get_content=lambda: "Emprego: 100 mil pessoas em 2020; 120 mil pessoas em 2021.")
    _, traces = calculate("Qual a variação?", frame, None,
                          _llm("percent_change", [{"row": 0, "column": column}, {"row": 1, "column": column}]), [node])
    assert traces[0]["result"] == "20,00 %"
    assert traces[0]["arithmetic_verified"]
    assert traces[0]["semantic_status"] == "requires_review"
    assert traces[0]["operands"][0]["sources"][0]["node_id"] == "original"


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
