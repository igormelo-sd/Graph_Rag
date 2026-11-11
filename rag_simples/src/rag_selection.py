"""Seleção global e contexto documental indivisível, sem chamadas LLM."""
import json
import re
from collections import defaultdict
from copy import copy

from domain_ontology import facets, filter_candidates, node_observations
from provenance import format_source_context, source_file
from runtime import bounded_int, context_token_budget, estimate_tokens
from logger import get_logger

log = get_logger(__name__)


def node_key(node):
    inner = getattr(node, "node", node)
    return str(getattr(inner, "node_id", None) or id(inner))


def coverage(node):
    result = defaultdict(set)
    for observation in node_observations(node):
        for key, values in observation["dimensions"].items():
            result[key].update(values)
    return result


def fuse(lists, question, reranker=None):
    """RRF entre listas; scores de fontes diferentes não são comparados."""
    scores, nodes = defaultdict(float), {}
    for items in lists:
        seen = set()
        for rank, node in enumerate(filter_candidates(items, question), 1):
            key = node_key(node)
            if key in seen:
                continue
            seen.add(key)
            scores[key] += 1 / (60 + rank)
            nodes.setdefault(key, node)
    ranked = []
    for key in sorted(nodes, key=lambda k: -scores[k]):
        item = copy(nodes[key])
        if hasattr(item, "score"):
            item.score = scores[key]
        ranked.append(item)
    if reranker and ranked:
        try:
            # Mantém os candidatos não reranqueados para cobertura posterior.
            top = reranker.postprocess_nodes(ranked[:80], query_str=question)
            ids = {node_key(n) for n in top}
            ranked = list(top) + [n for n in ranked if node_key(n) not in ids]
        except Exception as exc:
            log.warning("Reranking global indisponível; preservando RRF: %s", exc)
    # Conteúdo idêntico na mesma página é repetição; outras fontes são preservadas.
    unique, seen = [], set()
    for node in ranked:
        md = getattr(node, "metadata", {}) or {}
        signature = (source_file(node), str(md.get("page")),
                     re.sub(r"\s+", " ", node.get_content()).strip())
        if signature not in seen:
            seen.add(signature)
            unique.append(node)
    # Sobreposição integral: só elimina trecho contido na mesma página e com
    # os mesmos qualificadores; sobreposição parcial não é removida.
    result = []
    for node in unique:
        md = getattr(node, "metadata", {}) or {}
        text = re.sub(r"\s+", " ", node.get_content()).strip()
        duplicate = False
        if len(text) >= 100 and md.get("type") == "text":
            for other in result:
                om = getattr(other, "metadata", {}) or {}
                if source_file(other) == source_file(node) and str(om.get("page")) == str(md.get("page")) \
                        and all(om.get(k) == md.get(k) for k in ("type", "section", "raptor_level")) \
                        and text in re.sub(r"\s+", " ", other.get_content()):
                    duplicate = True
                    break
        if not duplicate:
            result.append(node)
    return result


def select_coverage(nodes, question, limit):
    """Reserva evidências para cada dimensão solicitada antes da diversidade."""
    wanted = facets(question)
    missing = {(k, v) for k in ("indicator", "region", "period", "sector") for v in wanted[k]}
    remaining, selected = list(nodes), []
    covered = {node_key(n): {(k, v) for k, values in coverage(n).items() for v in values} for n in remaining}
    while missing and remaining and len(selected) < limit:
        best = max(remaining, key=lambda n: len(missing & covered[node_key(n)]))
        hits = missing & covered[node_key(best)]
        if not hits:
            break
        selected.append(best)
        remaining.remove(best)
        missing -= hits
    # Diversidade é secundária à cobertura, nunca um limite rígido por arquivo.
    counts = defaultdict(int)
    for n in selected:
        counts[source_file(n)] += 1
    overflow = []
    for n in remaining:
        if counts[source_file(n)] < 3:
            selected.append(n)
            counts[source_file(n)] += 1
        else:
            overflow.append(n)
    return (selected + overflow)[:limit]


def sufficiency(question, nodes):
    """Cobertura candidata por observações, não prova de correção semântica."""
    wanted = facets(question)
    observations = [obs for node in nodes for obs in node_observations(node)]
    missing = {}
    # Exige os recortes em uma mesma observação; união de chunks não prova suporte.
    for key in ("indicator", "region", "period", "sector"):
        absent = []
        for value in wanted[key]:
            if not any(value in obs["dimensions"].get(key, []) and all(
                not wanted[other] or bool(set(obs["dimensions"].get(other, [])) & wanted[other])
                for other in ("indicator", "region", "period", "sector") if other != key
            ) for obs in observations):
                absent.append(value)
        if absent:
            missing[key] = sorted(absent)
    return {"status": "partial" if missing else "candidate_coverage" if observations else "unknown",
            "missing": missing, "semantic_verified": False}


def literal_context(node):
    block = format_source_context(node)
    raw = (getattr(node, "metadata", {}) or {}).get("table_structure")
    if raw:
        try:
            structure = json.loads(raw)
            block += "\nTítulo literal: " + str(structure.get("title", ""))
            block += "\nNotas literais: " + "\n".join(map(str, structure.get("notes", [])))
        except (TypeError, ValueError, AttributeError):
            pass
    return block


def pack_context(nodes, question, bundles=(), neighbors=None):
    """Não corta células, parágrafos ou notas para preencher orçamento."""
    budget = context_token_budget()
    parts, included = [], []
    selected_ids = set()
    consumed = 0
    ranked = select_coverage(nodes, question, bounded_int("RAG_FINAL_TOP_N", 30, 5, 80))
    order = {node_key(n): i for i, n in enumerate(ranked)}
    bundles = sorted(bundles, key=lambda b: min((order.get(node_key(n), len(ranked)) for n in b[1]), default=len(ranked)))
    # Dados calculados são um único bloco com TODAS as fontes de origem.
    units = []
    for text, origins in bundles:
        if not text or not origins:
            continue
        if {node_key(n) for n in filter_candidates(origins, question)} != {node_key(n) for n in origins}:
            continue
        block = "[Dados estruturados e fontes literais]\n" + text + "\n\n" + "\n\n".join(literal_context(n) for n in origins)
        units.append((block, list(origins), min((order.get(node_key(n), len(ranked)) for n in origins), default=len(ranked))))
    for n in ranked:
        if node_key(n) in selected_ids:
            continue
        origins = [n] + [candidate for candidate in (neighbors or {}).get(node_key(n), [])
                         if node_key(candidate) not in selected_ids]
        block = "\n\n".join(literal_context(origin) for origin in origins)
        units.append((block, origins, order[node_key(n)]))
    wanted = facets(question)
    missing = {(key, value) for key in ("indicator", "region", "period", "sector") for value in wanted[key]}
    covered = {node_key(n): {(k, v) for k, values in coverage(n).items() for v in values}
               for unit in units for n in unit[1]}
    while units:
        fitting = [u for u in units if consumed + estimate_tokens(u[0] + "\n\n") <= budget
                   and (u[0].startswith("[Dados estruturados") or any(node_key(n) not in selected_ids for n in u[1]))]
        if not fitting:
            break
        def hits(unit):
            return missing & set().union(*(covered[node_key(n)] for n in unit[1]))
        unit = min(fitting, key=lambda u: (-len(hits(u)), u[2], estimate_tokens(u[0])))
        units.remove(unit)
        parts.append(unit[0])
        consumed += estimate_tokens(unit[0] + "\n\n")
        missing -= hits(unit)
        for origin in unit[1]:
            if node_key(origin) not in selected_ids:
                included.append(origin)
                selected_ids.add(node_key(origin))
    return "\n\n".join(parts), included


def literal_table_payload(nodes):
    """Reutiliza células originais somente quando toda a seleção é estruturada."""
    from structured_output import MAX_ROWS, MAX_COLUMNS
    columns, rows, seen = None, [], set()
    for node in nodes:
        try:
            table = json.loads((getattr(node, "metadata", {}) or {})["table_structure"])
            headers = table["columns"]
            if not isinstance(headers, list) or not headers or len(headers) > MAX_COLUMNS or len(set(map(str, headers))) != len(headers):
                return None
            if columns is not None and columns != headers:
                return None  # Não combina esquemas diferentes por inferência.
            columns = headers
            for index, row in enumerate(table["rows"]):
                original = table.get("row_indices", list(range(len(table["rows"]))))[index]
                key = (source_file(node), str((getattr(node, "metadata", {}) or {}).get("page")),
                       table.get("table_id", node_key(node)), original)
                if len(row) != len(columns):
                    return None
                if key not in seen:
                    seen.add(key)
                    rows.append(row)
                    if len(rows) > MAX_ROWS:
                        return None
        except (TypeError, ValueError, KeyError, IndexError):
            return None
    return {"columns": columns, "rows": rows} if columns and rows else None
