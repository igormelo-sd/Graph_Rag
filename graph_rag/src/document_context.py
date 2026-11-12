"""Contexto documental literal, com associação auditável e sem enriquecimento LLM."""
import hashlib
import json
import re


def table_identity(metadata, text):
    raw = f"{metadata.get('source_file')}:{metadata.get('page')}:{metadata.get('table_index', '')}:{text}"
    return "table:" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def pdf_table_context(page, bbox):
    """Seleciona título/notas fora da caixa; geometria é vínculo candidato, não prova."""
    if not bbox or len(bbox) != 4:
        return {}
    x0, bottom, x1, top = (float(v) for v in bbox)
    y0, y1 = float(page.rect.height) - top, float(page.rect.height) - bottom
    candidates = {"title": [], "notes": []}
    for block in page.get_text("blocks"):
        bx0, by0, bx1, by1, text = block[:5]
        text = str(text).strip()
        overlap = max(0, min(x1, bx1) - max(x0, bx0))
        if not text or overlap <= 0:
            continue
        if by1 <= y0 and y0 - by1 <= 90 and re.match(r"(?i)^(?:tabela|quadro)\s+\d+\b", text):
            candidates["title"].append((y0 - by1, text))
        if by0 >= y1 and by0 - y1 <= 80 and re.match(r"(?i)^(?:nota(?:s)?|fonte|obs(?:ervação)?)[\s:.(]", text):
            candidates["notes"].append((by0 - y1, text))
    titles = sorted(candidates["title"])
    if not titles and not candidates["notes"]:
        return {}
    return {"title": titles[0][1][:1500] if titles else "",
            "notes": [text[:1500] for _, text in sorted(candidates["notes"])[:4]],
            "association": "literal_caption_and_spatial_candidate", "requires_review": True}


def structure_payload(columns, rows, metadata, title="", notes=(), row_indices=None):
    return json.dumps({"columns": [str(c) for c in columns],
                       "rows": [[str(v) for v in row] for row in rows],
                       "row_indices": row_indices if row_indices is not None else list(range(len(rows))),
                       "title": title, "notes": list(notes),
                       "table_id": metadata.get("table_key", ""),
                       "association": metadata.get("table_context_association", "literal_in_table"),
                       "context_requires_review": bool(metadata.get("table_context_requires_review", False))}, ensure_ascii=False)


def context_links(nodes):
    """Vínculos entre tabela e chunks que contêm literalmente título/nota/referência."""
    from collections import defaultdict
    by_page = defaultdict(list)
    for node in nodes:
        md = node.metadata
        by_page[(str(md.get("source_file", "")), str(md.get("page", "")))].append(node)
    for page_nodes in by_page.values():
        narrative = [n for n in page_nodes if n.metadata.get("type", "text") == "text"]
        for table in [n for n in page_nodes if n.metadata.get("type") == "table"]:
            md = table.metadata
            title = str(md.get("table_title", ""))
            try:
                notes = json.loads(md.get("table_notes", "[]"))
            except (TypeError, ValueError):
                notes = []
            literals = [("TEM_TITULO", title)] + [("TEM_NOTA", note) for note in notes if isinstance(note, str)]
            for relation, literal in literals:
                # Identificar começo do bloco; o bloco completo pode atravessar chunks.
                anchor = literal.splitlines()[0].strip() if literal else ""
                if len(anchor) < 8:
                    continue
                for target in narrative:
                    if anchor in target.text:
                        yield table, target, relation, {"evidence": anchor, "method": "literal_same_page",
                                                       "semantic_status": "requires_review" if md.get("table_context_requires_review") else "documentary_link"}
            marker = re.match(r"(?i)^(?:tabela|quadro)\s+\d+\b", title)
            if marker:
                for target in narrative:
                    if re.search(r"(?i)\b" + re.escape(marker.group()) + r"\b", target.text) and title.splitlines()[0] not in target.text:
                        yield table, target, "DESCRITA_EM", {"evidence": marker.group(), "method": "explicit_table_reference_same_page",
                                                             "semantic_status": "requires_review"}
