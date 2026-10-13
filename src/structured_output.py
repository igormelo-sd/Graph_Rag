"""Validação de saídas JSON tabulares produzidas por LLMs.

Este módulo substitui a antiga execução de Python gerado pelo modelo nos
retrievers de tabelas e séries temporais. A saída aceita é deliberadamente
pequena: colunas + linhas, ou um dicionário simples ``data``.
"""
from __future__ import annotations

import json
import re
from typing import Any

import pandas as pd

MAX_ROWS = 500
MAX_COLUMNS = 50
MAX_CELL_CHARS = 5_000
MAX_RESULT_CHARS = 20_000

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)


class StructuredOutputError(ValueError):
    """Saída do LLM ausente, inválida ou acima dos limites permitidos."""


def parse_json_object(raw: str) -> dict[str, Any]:
    """Extrai e valida um único objeto JSON de uma resposta textual."""
    if not isinstance(raw, str) or not raw.strip():
        raise StructuredOutputError("Resposta estruturada vazia.")

    text = raw.strip()
    fenced = _FENCE_RE.match(text)
    if fenced:
        text = fenced.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise StructuredOutputError("Objeto JSON não encontrado.")

    try:
        payload = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise StructuredOutputError("Objeto JSON inválido.") from exc
    if not isinstance(payload, dict):
        raise StructuredOutputError("A saída deve ser um objeto JSON.")
    return payload


def _validate_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > MAX_CELL_CHARS:
            raise StructuredOutputError("Célula textual acima do limite permitido.")
        return value
    raise StructuredOutputError("Células devem conter apenas valores escalares.")


def _validate_data_mapping(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or not data:
        raise StructuredOutputError("O campo 'data' deve ser um objeto não vazio.")
    if len(data) > MAX_ROWS:
        raise StructuredOutputError("Dicionário acima do limite de itens.")

    validated: dict[str, Any] = {}
    for key, value in data.items():
        key_text = str(key)
        if len(key_text) > MAX_CELL_CHARS:
            raise StructuredOutputError("Chave textual acima do limite permitido.")
        if isinstance(value, list):
            if len(value) > MAX_ROWS:
                raise StructuredOutputError("Lista acima do limite de itens.")
            validated[key_text] = [_validate_scalar(item) for item in value]
        else:
            validated[key_text] = _validate_scalar(value)
    return validated


def tabular_payload(payload: dict[str, Any]) -> tuple[pd.DataFrame | None, dict | None]:
    """Converte JSON validado em DataFrame ou dicionário simples."""
    if "rows" not in payload:
        return None, _validate_data_mapping(payload.get("data"))

    rows = payload.get("rows")
    columns = payload.get("columns")
    if not isinstance(rows, list) or not rows:
        raise StructuredOutputError("O campo 'rows' deve ser uma lista não vazia.")
    if len(rows) > MAX_ROWS:
        raise StructuredOutputError("Tabela acima do limite de linhas.")

    if rows and all(isinstance(row, dict) for row in rows):
        normalized_rows = [
            {str(key): _validate_scalar(value) for key, value in row.items()}
            for row in rows
        ]
        inferred_columns = list(normalized_rows[0])
        if len(inferred_columns) > MAX_COLUMNS:
            raise StructuredOutputError("Tabela acima do limite de colunas.")
        if any(set(row) != set(inferred_columns) for row in normalized_rows):
            raise StructuredOutputError("As linhas devem possuir as mesmas colunas.")
        return pd.DataFrame(normalized_rows, columns=inferred_columns), None

    if not isinstance(columns, list) or not columns:
        raise StructuredOutputError("'columns' é obrigatório para linhas posicionais.")
    if len(columns) > MAX_COLUMNS or len(set(map(str, columns))) != len(columns):
        raise StructuredOutputError("Colunas inválidas, duplicadas ou acima do limite.")
    normalized_columns = [str(column) for column in columns]

    normalized_rows = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(normalized_columns):
            raise StructuredOutputError("Linha com quantidade incorreta de células.")
        normalized_rows.append([_validate_scalar(value) for value in row])
    return pd.DataFrame(normalized_rows, columns=normalized_columns), None


def result_text(payload: dict[str, Any]) -> str:
    """Obtém o campo textual ``resultado`` com limite de tamanho."""
    result = payload.get("resultado")
    if not isinstance(result, str) or not result.strip():
        raise StructuredOutputError("O campo 'resultado' deve ser texto não vazio.")
    result = result.strip()
    if len(result) > MAX_RESULT_CHARS:
        raise StructuredOutputError("Resultado acima do limite permitido.")
    return result
