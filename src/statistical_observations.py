"""Observações por célula, preservando cabeçalhos, linha e notas literais."""
import hashlib
import json
import re
from numbers import Number

from domain_ontology import facets, periods, territories

DIMENSIONS = ("indicator", "region", "period", "unit", "scale", "sector", "source", "basis", "coverage", "kind")
DATE_LABEL = re.compile(r"(?i)^(?:ano|per[ií]odo|data|m[eê]s|trimestre|c[oó]digo|cnae|publica[cç][aã]o|divulga[cç][aã]o|edi[cç][aã]o|atualiza[cç][aã]o)\b")
PUBLICATION_LABEL = re.compile(r"(?i)\b(?:publica[cç][aã]o|publicado|edi[cç][aã]o|divulga[cç][aã]o|divulgado|atualiza[cç][aã]o|atualizado)\b")


def reference_text(text):
    """Datas de publicação ficam em atributo separado, não período de referência."""
    return "\n".join(line for line in str(text).splitlines()
                     if not PUBLICATION_LABEL.search(line))


def publication_periods(text):
    return sorted({p for line in str(text).splitlines()
                   if PUBLICATION_LABEL.search(line)
                   for p in periods(line)})


def numeric_literal(value):
    if isinstance(value, Number) and not isinstance(value, bool):
        return True
    return bool(re.fullmatch(r"[-−]?\d+(?:\.\d{3})*(?:,\d+)?\s*%?", str(value).strip()))


def table_observations(text, metadata, node_id):
    raw = metadata.get("table_structure")
    if not raw:
        return None
    try:
        structure = json.loads(raw)
        columns, rows = structure["columns"], structure["rows"]
        if not isinstance(columns, list) or not isinstance(rows, list):
            return None
    except (TypeError, ValueError, KeyError):
        return None
    title = str(structure.get("title", ""))
    notes = [str(n) for n in structure.get("notes", [])]
    # Apenas conteúdo documental literal: não table_descricao/periodo gerados pelo LLM.
    shared = facets(reference_text(title + "\n" + "\n".join(notes)))
    source_notes = "\n".join(notes)
    # Fonte institucional nas notas, distinta do nome do arquivo.
    shared["source"] |= facets(re.sub(r"(?im)^fonte\s*:", "", source_notes))["source"]
    publication = publication_periods(title + "\n" + source_notes)
    records = []
    cursor = 0
    row_indices = structure.get("row_indices", list(range(len(rows))))
    for row_number, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != len(columns):
            continue
        row_literals = [f"{header}: {value}" for header, value in zip(columns, row) if str(value).strip()]
        row_text = "\n".join(row_literals)
        row_start = str(text).find(row_text, cursor)
        if row_start < 0:
            # Fonte textual alterada: não reutilizar offsets de outra versão.
            continue
        cursor = row_start + len(row_text)
        context_cells = [f"{header}: {value}" for header, value in zip(columns, row)
                         if (DATE_LABEL.search(str(header)) or not numeric_literal(value))
                         and not PUBLICATION_LABEL.search(str(header))]
        row_facets = facets(reference_text(" ".join(context_cells)))
        # Cabeçalhos não temporais podem fornecer indicador/unidade comuns às colunas anuais.
        header_facets = facets(" ".join(str(c) for c in columns if not periods(str(c)) and not DATE_LABEL.search(str(c))))
        for column_number, (header, value) in enumerate(zip(columns, row)):
            header, raw_value = str(header), str(value)
            value = raw_value.strip()
            if not numeric_literal(value) or DATE_LABEL.search(header):
                continue
            own = facets(reference_text(header + " " + value))
            cell_period = periods(reference_text(header))
            binding = {}
            for key in DIMENSIONS:
                if key == "period":
                    # Ano da coluna prevalece sobre outros anos da tabela.
                    selected = cell_period or row_facets[key] or shared[key]
                else:
                    selected = own[key] | row_facets[key]
                    if not selected:
                        selected = shared[key] or header_facets[key]
                binding[key] = sorted(selected)
            if not binding["indicator"]:
                continue
            _, ambiguities = territories(reference_text(header + " " + " ".join(context_cells) + " " + title))
            issues = [f"{k}: ausente ou ambíguo" for k in ("indicator", "region", "period", "unit") if len(binding[k]) != 1] + ambiguities
            issues.extend(f"{key}: ambíguo" for key, values in binding.items() if key not in {"indicator", "region", "period", "unit"} and len(values) > 1)
            if structure.get("context_requires_review"):
                issues.append("contexto da tabela: associação candidata")
            cell_line = f"{header}: {raw_value}"
            line_offset = row_text.find(cell_line)
            if line_offset < 0:
                continue
            start = row_start + line_offset + len(header) + 2 + len(raw_value) - len(raw_value.lstrip())
            original_row = row_indices[row_number] if row_number < len(row_indices) else row_number
            identity = f"{node_id}:cell:{original_row}:{column_number}:{value}"
            records.append({"id": "obs:" + hashlib.sha256(identity.encode()).hexdigest()[:24],
                            "value": value, "dimensions": binding, "issues": sorted(set(issues)),
                            "status": "requires_review" if issues else "structured_candidate", "method": "literal_table_cell",
                            "publication_periods": sorted(set(publication) | {p for h, v in zip(columns, row)
                                if PUBLICATION_LABEL.search(str(h)) for p in periods(str(v))}),
                            "provenance": {"node_id": node_id, "file": metadata.get("source_file", ""), "page": metadata.get("page"),
                                           "start": start, "end": start + len(value), "excerpt": row_text[:1800],
                                           "table_id": structure.get("table_id", ""), "row": original_row, "column": column_number,
                                           "header": header, "row_labels": context_cells, "title": title, "notes": notes,
                                           "context_association": structure.get("association", "literal_in_table")}})
            if len(records) >= 200:
                return records
    return records
