"""Localiza o arquivo de resultado de uma pergunta e versão, inclusive em rodadas com nomes antigos.

As rodadas anteriores a 12/11/2026 gravaram `<id>_rag_simples.json`, `<id>_graphrag.json`
e `<id>_rag_pais.json`; as novas usam `simple_rag`, `graph_rag` e `parent_rag`.
"""
from pathlib import Path

LEGACY_NAMES = {"simple_rag": "rag_simples", "graph_rag": "graphrag", "parent_rag": "rag_pais"}


def result_file(directory, question_id, variant) -> Path:
    """Caminho do resultado; aceita o nome novo e o antigo, preferindo o novo."""
    directory = Path(directory)
    current = directory / f"{question_id}_{variant}.json"
    legacy = LEGACY_NAMES.get(variant)
    if not current.exists() and legacy:
        old = directory / f"{question_id}_{legacy}.json"
        if old.exists():
            return old
    return current
