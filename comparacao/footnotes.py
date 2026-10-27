"""Rodapés de planilhas: linhas de nota viram notas da tabela, não trechos próprios.

Planilhas trazem "Fonte: ...", "Nota: ..." e "(1) ..." como linhas com uma única
célula preenchida. Indexadas como trechos, elas competem na busca sem conter
dado algum. Aqui elas saem do índice e passam a acompanhar as demais linhas da
mesma tabela em `table_footnotes` (JSON), que o contexto final mostra ao modelo.
"""
import json
import re

FOOTNOTE = re.compile(r"^\s*(fontes?\b|notas?\b|obs\b|elabora[cç][aã]o\b|\(\d+\)|\(\.\.\.\)|\*)", re.IGNORECASE)
EMPTY = {"", "nan", "none"}


def row_values(node):
    """Valores preenchidos de um trecho de linha de tabela, sem a linha final de origem."""
    source = str(node.metadata.get("source_file", ""))
    values = []
    for line in node.text.split("\n"):
        if line == f"Fonte: {source}" or "]: " not in line:
            continue
        value = line.split("]: ", 1)[1].strip()
        if value.lower() not in EMPTY:
            values.append(value)
    return values


def footnote_text(node):
    """Texto da nota quando o trecho é uma linha de rodapé; None caso contrário."""
    if node.metadata.get("type") != "table" or node.metadata.get("chunk_strategy") != "row_per_chunk":
        return None
    values = row_values(node)
    return values[0] if len(values) == 1 and FOOTNOTE.match(values[0]) else None


def separate_table_footnotes(nodes):
    """Remove linhas de rodapé e anexa suas notas às linhas da mesma tabela.

    Retorna os nós restantes e a quantidade de rodapés removidos.
    """
    notes, kept = {}, []
    for node in nodes:
        note = footnote_text(node)
        if note is None:
            kept.append(node)
            continue
        table = node.metadata.get("table_key")
        if note not in notes.setdefault(table, []):
            notes[table].append(note)
    for node in kept:
        table_notes = notes.get(node.metadata.get("table_key"))
        if node.metadata.get("type") == "table" and table_notes:
            node.metadata["table_footnotes"] = json.dumps(table_notes, ensure_ascii=False)
    return kept, len(nodes) - len(kept)
