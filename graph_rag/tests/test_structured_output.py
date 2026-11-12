"""Testes da saída JSON usada por tabelas e séries temporais."""
import pytest

from structured_output import (
    StructuredOutputError,
    parse_json_object,
    result_text,
    tabular_payload,
)


def test_tabela_posicional_valida():
    payload = parse_json_object(
        '```json\n{"columns":["Período","Valor"],"rows":[["2024",1.2]]}\n```'
    )
    df, data = tabular_payload(payload)
    assert data is None
    assert list(df.columns) == ["Período", "Valor"]
    assert df.iloc[0]["Valor"] == 1.2


def test_dicionario_simples_valido():
    df, data = tabular_payload({"data": {"2023": 1.0, "2024": 1.2}})
    assert df is None
    assert data == {"2023": 1.0, "2024": 1.2}


def test_resultado_textual_valido():
    assert result_text({"resultado": "A variação foi 0,2 p.p."}) == "A variação foi 0,2 p.p."


@pytest.mark.parametrize("raw", ["", "sem json", "[]", "{invalido}"])
def test_json_invalido_rejeitado(raw):
    with pytest.raises(StructuredOutputError):
        parse_json_object(raw)


def test_objetos_aninhados_em_celulas_sao_rejeitados():
    with pytest.raises(StructuredOutputError):
        tabular_payload({"columns": ["x"], "rows": [[{"arquivo": "/etc/passwd"}]]})
