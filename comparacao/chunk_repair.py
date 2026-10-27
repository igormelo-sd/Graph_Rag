"""Reparos de trechos no preparo, comuns às duas versões.

- Fragmentos curtos de texto (quebras de página do PDF) ficam sem contexto e não
  são encontrados. O texto deles também é anexado ao trecho anterior da mesma
  fonte. O fragmento continua no índice, para não alterar a sequência de
  `chunk_id` usada pelas arestas estruturais do grafo.
- Tabelas pequenas que o processamento dividiu em uma linha por trecho voltam a
  ser um único trecho quando cabem no limite de caracteres, preservando o
  contexto entre linhas (por exemplo, dicionários de variáveis).
"""


def join_short_fragments(nodes, min_chars):
    """Anexa fragmentos de texto curtos ao trecho de texto anterior da mesma fonte."""
    if min_chars <= 0:
        return nodes, 0
    joined, previous = 0, {}
    for node in nodes:
        if node.metadata.get("type", "text") != "text":
            continue
        source = node.metadata.get("source_file")
        before = previous.get(source)
        if len(node.text.strip()) < min_chars and before is not None:
            # Fragmentos seguidos vão todos para o último trecho completo.
            before.text = f"{before.text}\n{node.text.strip()}"
            joined += 1
        else:
            previous[source] = node
    return nodes, joined


def merge_small_tables(nodes, max_rows, max_chars):
    """Une as linhas de tabelas pequenas em um trecho `full_table`."""
    if max_rows <= 0:
        return nodes, 0
    groups = {}
    for node in nodes:
        if node.metadata.get("type") == "table" and node.metadata.get("chunk_strategy") == "row_per_chunk":
            groups.setdefault(node.metadata.get("table_key"), []).append(node)
    merged_tables, replaced = 0, {}
    for rows in groups.values():
        text = "\n---\n".join(row.text for row in rows)
        if len(rows) > max_rows or len(text) > max_chars:
            continue
        first = rows[0]
        first.text = text
        # A estrutura por linha deixa de valer para o trecho unido.
        first.metadata = {key: value for key, value in first.metadata.items() if key != "table_structure"}
        first.metadata.update(chunk_strategy="full_table", merged_rows=len(rows))
        replaced.update({id(row): first for row in rows})
        merged_tables += 1
    kept, seen = [], set()
    for node in nodes:
        target = replaced.get(id(node), node)
        if id(target) not in seen:
            seen.add(id(target))
            kept.append(target)
    return kept, merged_tables
