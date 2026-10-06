"""Modelo declarativo compartilhado. Conformidade não prova verdade documental."""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from datetime import date
from functools import lru_cache
from pathlib import Path

SCHEMA_VERSION = "economic-observations-v2"
TERRITORIES = {
    "brasil": {"name": "Brasil", "type": "Territorio", "parent": None},
    "estado_sp": {"name": "Estado de São Paulo", "type": "Estado", "parent": "brasil"},
    "municipio_sp": {"name": "Município de São Paulo", "type": "Municipio", "parent": "estado_sp"},
    "rmsp": {"name": "Região Metropolitana de São Paulo", "type": "Região", "parent": "estado_sp"},
    "interior_sp": {"name": "Interior paulista", "type": "Região", "parent": "estado_sp"},
}


def fold(text):
    return "".join(c for c in unicodedata.normalize("NFD", str(text).lower()) if unicodedata.category(c) != "Mn")


CLASSES = {
    "Indicador": "Conceito medido; não confundir com um valor observado.",
    "ObservacaoEstatistica": "Valor documental associado a indicador, unidade e recortes explícitos.",
    "Comparacao": "Operação entre observações, com base e fórmula explícitas.",
    "OperandoCalculo": "Valor selecionado para uma operação, associado a evidências e observações candidatas.",
    "Territorio": "Recorte geográfico identificado sem equiparar estado e município.",
    "Região": "Agrupamento territorial definido pela fonte.",
    "Estado": "Unidade federativa.", "Municipio": "Município identificado.",
    "Setor": "Atividade econômica ou agrupamento setorial da fonte.",
    "Período": "Intervalo de referência do dado; não data de publicação.",
    "Unidade": "Unidade de medida, distinta de escala e tipo de medida.",
    "FonteDados": "Base estatística ou instituição citada no trecho.",
    "Documento": "Arquivo documental.", "Pagina": "Página/aba de um documento.",
    "Chunk": "Trecho indexado com ID e proveniência.",
    "Tabela": "Tabela extraída.", "Grafico": "Figura/gráfico extraído.",
}
PARENTS = {"Estado": "Territorio", "Municipio": "Territorio", "Região": "Territorio"}
# Origem/destino são regras de conformidade da aplicação, não axiomas OWL.
RELATIONS = {
    "OBSERVACAO_DE": (["ObservacaoEstatistica"], ["Indicador"]),
    "REFERENTE_A": (["ObservacaoEstatistica", "Comparacao"], ["Período"]),
    "APLICA_SE_A": (["ObservacaoEstatistica", "Comparacao"], ["Territorio"]),
    "NO_SETOR": (["ObservacaoEstatistica"], ["Setor"]),
    "EXPRESSA_EM": (["ObservacaoEstatistica"], ["Unidade"]),
    "MEDIDO_POR": (["ObservacaoEstatistica", "Indicador"], ["FonteDados"]),
    "SUSTENTADA_POR": (["ObservacaoEstatistica", "Comparacao", "OperandoCalculo"], ["Chunk"]),
    "BASE_DE": (["ObservacaoEstatistica", "OperandoCalculo"], ["Comparacao"]),
    "FINAL_DE": (["ObservacaoEstatistica", "OperandoCalculo"], ["Comparacao"]),
    "OPERANDO_DE": (["OperandoCalculo"], ["Comparacao"]),
    "BASEADO_EM": (["OperandoCalculo"], ["ObservacaoEstatistica"]),
    "PARTE_DE": (["Territorio", "Setor"], ["Territorio", "Setor"]),
    "CRESCEU_EM": (["Comparacao"], ["Período"]),
    "RECUOU_EM": (["Comparacao"], ["Período"]),
    "PERTENCE_A": (["ObservacaoEstatistica"], ["Setor"]),
    "RELACIONA_COM": (["Indicador", "Setor"], ["Indicador", "Setor"]),
    "ASSOCIADO_A": (["Indicador"], ["Indicador"]),
    "CAUSA": (["Indicador"], ["Indicador"]),
    "CONTIDA_EM": (["Chunk", "Tabela", "Grafico"], ["Pagina"]),
    "PERTENCE_A_DOC": (["Pagina"], ["Documento"]),
    "DESCRITA_EM": (["Tabela", "Grafico"], ["Chunk"]),
    "TEM_TITULO": (["Tabela", "Grafico", "Chunk"], ["Chunk"]),
    "TEM_NOTA": (["Tabela", "Grafico", "Chunk"], ["Chunk"]),
    "REPRESENTADA_EM": (["Tabela", "Grafico"], ["Chunk"]),
    "NEXT_CHUNK": (["Chunk"], ["Chunk"]), "SAME_PAGE": (["Chunk"], ["Chunk"]),
}
INDICATORS = {
    "desocupacao": (r"desocupacao|desemprego", "Taxa de desocupação", "taxa"),
    "ocupacao": (r"(?<!des)ocupacao|pessoal ocupado|ocupados", "Ocupação", None),
    "pib": (r"\bpib\b|produto interno bruto", "Produto interno bruto", None),
    "exportacao": (r"exporta\w*", "Exportações", "fluxo"),
    "importacao": (r"importa\w*", "Importações", "fluxo"),
    "saldo": (r"\bsaldo\b", "Saldo", "saldo"),
    "rendimento": (r"rendimento|salario|\brenda\b", "Rendimento", None),
    "producao": (r"producao", "Produção", None),
    "emprego": (r"(?<!des)emprego\w*|postos de trabalho", "Emprego", None),
    "inflacao": (r"inflacao|\bipca\b", "Inflação", "taxa"),
    "participacao": (r"participacao", "Participação", "taxa"),
}
UNITS = {"percentual": r"%|por cento|percentual", "pp": r"p\.\s*p\.|pontos? percentuais?",
         "real": r"r\$|reais", "dolar": r"us\$|dolares", "pessoa": r"pessoas|trabalhadores|habitantes",
         "tonelada": r"toneladas?"}
SCALES = {"mil": r"\bmil\b|milhares", "milhao": r"milhao|milhoes", "bilhao": r"bilhao|bilhoes"}
SECTORS = {"industria": r"industria|industrial", "comercio": r"comercio|comercial",
           "servicos": r"servicos", "agropecuaria": r"agropecuaria|agricultura", "construcao": r"construcao"}
SECTORS.update({"industria_transformacao": r"industria de transformacao", "industria_extrativa": r"industria extrativa"})
SECTOR_PARENTS = {"industria_transformacao": "industria", "industria_extrativa": "industria"}
SECTOR_LABELS = {"industria": "Indústria", "comercio": "Comércio", "servicos": "Serviços", "agropecuaria": "Agropecuária",
                 "construcao": "Construção", "industria_transformacao": "Indústria de transformação", "industria_extrativa": "Indústria extrativa"}
SOURCES = {"caged": r"\bcaged\b", "pnadc": r"\bpnad\w*\b", "rais": r"\brais\b", "seade": r"\bseade\b", "ibge": r"\bibge\b"}
MONTHS = "janeiro fevereiro marco abril maio junho julho agosto setembro outubro novembro dezembro".split()
MONTH_LABELS = (r"jan(?:eiro)?", r"fev(?:ereiro)?", r"mar(?:co)?", r"abr(?:il)?", r"mai(?:o)?", r"jun(?:ho)?", r"jul(?:ho)?", r"ago(?:sto)?", r"set(?:embro)?", r"out(?:ubro)?", r"nov(?:embro)?", r"dez(?:embro)?")
NUMBER = re.compile(r"(?<![\w])([-−]?\d+(?:\.\d{3})*(?:,\d+)?\s*%?)(?![\w])")
NUMERIC_PERIOD = re.compile(r"\b(?:(?:19|20)\d{2}-\d{1,2}(?:-\d{1,2})?|\d{1,2}[/-](?:\d{1,2}[/-])?(?:19|20)\d{2})\b")


def enabled():
    return os.getenv("RAG_ONTOLOGY_ENABLE", "1").lower() in {"1", "true", "yes", "on"}


def approved_extensions():
    path = Path(os.getenv("RAG_ONTOLOGY_EXTENSIONS") or Path(__file__).resolve().parents[1] / "config" / "ontology_extensions.json")
    if not path.exists():
        return {}
    return _extensions_from_text(path.read_text(encoding="utf-8-sig"))


@lru_cache(maxsize=8)
def _extensions_from_text(raw):
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Extensões devem ser objeto JSON")
    if data.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION or not isinstance(data.get("entity_types", []), list):
        raise ValueError("Versão/estrutura das extensões incompatível")
    output = {}
    for item in data.get("entity_types", []):
        if not isinstance(item, dict):
            raise ValueError("Tipo de extensão inválido")
        if item.get("reviewed") is not True:
            continue
        name = item.get("name", "")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Z][A-Za-z]{2,39}", name) or name in CLASSES or not isinstance(item.get("parent"), str) or item["parent"] not in CLASSES or not isinstance(item.get("description"), str) or not item["description"].strip():
            raise ValueError("Extensão de ontologia revisada inválida")
        output[name] = {"description": str(item["description"])[:1000], "parent": item["parent"]}
    return output


def entity_definitions():
    return {**CLASSES, **{name: item["description"] for name, item in approved_extensions().items()}}


def fingerprint():
    payload = {"version": SCHEMA_VERSION, "classes": CLASSES, "parents": PARENTS,
               "relations": RELATIONS, "indicators": INDICATORS, "units": UNITS,
               "scales": SCALES, "sectors": SECTORS, "sector_parents": SECTOR_PARENTS, "sector_labels": SECTOR_LABELS, "sources": SOURCES,
               "territories": TERRITORIES, "extensions": approved_extensions()}
    payload["period_formats"] = {"month_labels": MONTH_LABELS, "version": 2}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def is_type(actual, expected):
    while actual:
        if actual == expected:
            return True
        actual = PARENTS.get(actual) or approved_extensions().get(actual, {}).get("parent")
    return False


def validate_relation(subject_type, relation, object_type):
    rule = RELATIONS.get(relation)
    if relation == "PARTE_DE":
        return any(is_type(subject_type, kind) and is_type(object_type, kind) for kind in ("Territorio", "Setor"))
    return bool(rule and any(is_type(subject_type, t) for t in rule[0]) and any(is_type(object_type, t) for t in rule[1]))


def territories(text):
    text = fold(text)
    values, ambiguities = set(), []
    patterns = {"brasil": r"\bbrasil\b|brasileir\w*|nacional",
                "rmsp": r"\brmsp\b|regiao metropolitana de sao paulo",
                "interior_sp": r"interior (?:de sao paulo|paulista)",
                "municipio_sp": r"(?:municipio|cidade|capital) (?:de )?sao paulo|capital paulista",
                "estado_sp": r"estado (?:de )?(?:sao paulo|sp)\b|\buf\s*:?\s*sp\b"}
    occupied = []
    for key, pattern in patterns.items():
        for m in re.finditer(pattern, text):
            values.add(key)
            occupied.append(m.span())
    for m in re.finditer(r"sao paulo|\bsp\b|paulista", text):
        if not any(a <= m.start() and m.end() <= b for a, b in occupied):
            ambiguities.append("São Paulo/SP: recorte territorial não explícito")
    return values, sorted(set(ambiguities))


def periods(text):
    text = fold(text)
    result, occupied = set(), []
    for pattern, iso in ((r"\b((?:19|20)\d{2})-(\d{2})-(\d{2})\b", True),
                         (r"\b(\d{1,2})[/-](\d{1,2})[/-]((?:19|20)\d{2})\b", False)):
        for match in re.finditer(pattern, text):
            occupied.append(match.span())
            values = tuple(int(value) for value in match.groups())
            try:
                date_values = values if iso else (values[2], values[1], values[0])
                result.add(date(*date_values).isoformat())
            except ValueError:
                pass  # Data inválida não vira automaticamente um período anual.
    for pattern, iso in ((r"\b((?:19|20)\d{2})-(0[1-9]|1[0-2])\b", True),
                         (r"\b(0?[1-9]|1[0-2])[/-]((?:19|20)\d{2})\b", False)):
        for match in re.finditer(pattern, text):
            if any(a <= match.start() < b for a, b in occupied):
                continue
            year, month = match.groups() if iso else reversed(match.groups())
            result.add(f"{year}-{int(month):02d}")
            occupied.append(match.span())
    pattern = r"\b([1-4])(?:[ºo°]?\s*(?:trimestre|tri(?:m)?\.?|t))\s*(?:de\s*)?((?:19|20)\d{2})\b"
    for m in re.finditer(pattern, text):
        result.add(f"{m.group(2)}-Q{m.group(1)}")
        occupied.append(m.span())
    for index, month in enumerate(MONTH_LABELS, 1):
        for m in re.finditer(rf"\b{month}\.?\s*(?:de\s*|[/-]\s*)?((?:19|20)\d{{2}})\b", text):
            result.add(f"{m.group(1)}-{index:02d}")
            occupied.append(m.span())
    for m in re.finditer(r"\b(?:19|20)\d{2}\b", text):
        if not any(a <= m.start() < b for a, b in occupied):
            result.add(m.group())
    return result


def period_granularity(value):
    for name, pattern in (("year", r"\d{4}"), ("quarter", r"\d{4}-Q[1-4]"),
                          ("month", r"\d{4}-\d{2}"), ("day", r"\d{4}-\d{2}-\d{2}")):
        if re.fullmatch(pattern, value):
            return name
    return "unknown"


def facets(text):
    raw = fold(re.sub(r"(?im)^Fonte:.*$", "", str(text)))
    # Não tratar publicação/divulgação como período estatístico.
    raw = "\n".join(line for line in raw.splitlines() if not re.search(r"\b(?:publicacao|publicado|edicao|divulgacao|divulgado|atualizacao|atualizado)\b", line))
    region, _ = territories(raw)
    sectors = {k for k, p in SECTORS.items() if re.search(p, raw)}
    # A especialização explícita prevalece sobre a palavra genérica no mesmo rótulo.
    for child, parent in SECTOR_PARENTS.items():
        if child in sectors:
            sectors.discard(parent)
    return {"indicator": {k for k, (p, _, _) in INDICATORS.items() if re.search(p, raw)},
            "region": region, "period": periods(raw),
            "unit": {k for k, p in UNITS.items() if re.search(p, raw)},
            "scale": {k for k, p in SCALES.items() if re.search(p, raw)},
            "sector": sectors,
            "source": {k for k, p in SOURCES.items() if re.search(p, raw)},
            "basis": {k for k, p in {"real": r"\breal\b|deflacionad", "nominal": r"nominal", "dessazonalizado": r"dessazonalizad|ajuste sazonal"}.items() if re.search(p, raw)},
            "coverage": {k for k, p in {"formal": r"(?<!in)\bforma(?:l|is)\b|com carteira", "informal": r"\binforma(?:l|is)\b|sem carteira", "total": r"total"}.items() if re.search(p, raw)},
            "kind": {k for k, p in {"estoque": r"estoque", "saldo": r"saldo", "fluxo": r"admissoes|desligamentos|fluxo", "taxa": r"taxa", "variacao": r"variacao|crescimento|recuo|aumento|queda"}.items() if re.search(p, raw)}}


def query_constraints(text):
    dimensions = facets(text)
    _, ambiguous = territories(text)
    return {"schema_version": SCHEMA_VERSION, "schema_hash": fingerprint(),
            "dimensions": {k: sorted(v) for k, v in dimensions.items()}, "ambiguities": ambiguous}


def expand_query(text):
    if not enabled():
        return text
    additions = [label for key, (_, label, _) in INDICATORS.items()
                 if key in facets(text)["indicator"] and fold(label) not in fold(text)]
    additions.extend(TERRITORIES[key]["name"] for key in facets(text)["region"] if fold(TERRITORIES[key]["name"]) not in fold(text))
    return text + ("\nTermos equivalentes para busca: " + "; ".join(additions[:4]) if additions else "")


def preserve_query(original, rewritten):
    """Não aceita reescrita que altere recortes ou resolva ambiguidades sem evidência."""
    before, after = facets(original), facets(rewritten)
    if any(before[k] != after[k] for k in ("region", "period", "unit", "scale", "sector", "indicator", "kind", "basis", "coverage")):
        return original
    return rewritten


def prompt_block(question=""):
    if not enabled():
        return ""
    relevant = facets(question)["indicator"] if question else set()
    terms = {k: v for k, v in CLASSES.items() if k in {"Indicador", "ObservacaoEstatistica", "Comparacao", "Territorio", "Período", "Unidade"}}
    return "\n[Modelo de domínio; definições, não evidência]\n" + json.dumps(terms, ensure_ascii=False) + "\nNão equipare taxa, saldo, estoque e variação, nem município e estado. Preserve unidade, escala, período e cobertura. Campos ausentes permanecem desconhecidos. Relações extraídas são candidatas: preserve negação e incerteza, não converta correlação em causalidade. Pertencimento territorial/setorial não autoriza somar observações. " + json.dumps({k: INDICATORS[k][1] for k in sorted(relevant)}, ensure_ascii=False) + "\n"


def extract_observations(text, metadata=None, node_id=""):
    """Extração local conservadora por ocorrência; múltiplas dimensões não são combinadas."""
    if not enabled():
        return []
    metadata = metadata or {}
    from statistical_observations import table_observations, reference_text, publication_periods
    structured = table_observations(text, metadata, node_id)
    if structured is not None:
        return structured
    records = []
    # Linhas/tabelas estruturadas: cada bloco pode representar uma linha.
    blocks = re.split(r"\n---\n|(?<=[.!?])\s+(?=[A-ZÀ-Ú])", str(text))
    offset = 0
    for block in blocks:
        start = str(text).find(block, offset)
        offset = start + len(block)
        dimensions = facets(block)
        _, ambiguities = territories(block)
        date_spans = [match.span() for match in NUMERIC_PERIOD.finditer(block)]
        for match in NUMBER.finditer(block):
            value = match.group(1).strip()
            if any(start <= match.start() < end for start, end in date_spans):
                continue
            if re.match(r"[1-4](?:[ºo°]?\s*(?:trimestre|tri(?:m)?\.?|t))\s*(?:de\s*)?(?:19|20)\d{2}\b", fold(block[match.start():])):
                continue
            # Datas, IDs e referências documentais não são medidas.
            line_start = block.rfind("\n", 0, match.start()) + 1
            line_end = block.find("\n", match.end())
            line = block[line_start:line_end if line_end >= 0 else len(block)]
            if not reference_text(line):
                continue
            if re.search(r"\b(ano|periodo|data|fonte|pagina|codigo|cnae)\s*:", fold(line)) or re.fullmatch(r"(?:19|20)\d{2}", value) or value in periods(block):
                continue
            if not dimensions["indicator"]:
                continue
            local = facets(line)
            binding = {k: sorted(local[k] or dimensions[k]) for k in dimensions}
            missing = [k for k in ("indicator", "region", "period", "unit") if len(binding[k]) != 1]
            issues = [f"{k}: ausente ou ambíguo" for k in missing] + ambiguities
            issues.extend(f"{key}: ambíguo" for key, values in binding.items() if key not in {"indicator", "region", "period", "unit"} and len(values) > 1)
            identity = f"{node_id}:{start + match.start()}:{value}"
            records.append({"id": "obs:" + hashlib.sha256(identity.encode()).hexdigest()[:24],
                            "value": value, "dimensions": binding, "issues": issues,
                            "status": "requires_review" if issues else "structured_candidate",
                            "method": "local_heuristic", "provenance": {
                                "node_id": node_id, "file": metadata.get("source_file", ""), "page": metadata.get("page"),
                                "start": start + match.start(), "end": start + match.end(), "excerpt": line[:600]}})
            records[-1]["publication_periods"] = publication_periods(text)
            if len(records) >= 200:
                return records
    return records


def node_observations(node):
    inner = getattr(node, "node", node)
    metadata = getattr(inner, "metadata", {}) or {}
    try:
        if int(metadata.get("raptor_level", 0)) > 0:
            return []  # Resumos gerados não são novas observações documentais.
    except (TypeError, ValueError):
        return []
    return extract_observations(getattr(inner, "text", "") or node.get_content(),
                                metadata, str(getattr(inner, "node_id", "")))


def annotate_node(node):
    if not enabled():
        return
    records = node_observations(node)
    dimensions = facets(node.text)
    fields = {"ontology_version": SCHEMA_VERSION, "ontology_hash": fingerprint(),
              "ontology_facets": json.dumps({k: sorted(v) for k, v in dimensions.items()}, ensure_ascii=False),
              "ontology_observations": json.dumps(records, ensure_ascii=False)}
    fields.update({"ontology_" + key: next(iter(values)) for key, values in dimensions.items() if len(values) == 1})
    node.metadata.update(fields)
    # JSON contém evidências, não deve dominar o texto do embedding/prompts.
    excluded = list(fields) + ["table_structure"]
    node.excluded_embed_metadata_keys = list(dict.fromkeys(node.excluded_embed_metadata_keys + excluded))
    node.excluded_llm_metadata_keys = list(dict.fromkeys(node.excluded_llm_metadata_keys + excluded))


def filter_candidates(nodes, question):
    """Remove conflitos explícitos; dados incompletos permanecem para revisão."""
    if not enabled():
        return list(nodes)
    wanted = facets(question)
    from knowledge_analytics import hierarchy_scope
    scope = hierarchy_scope(question)
    output = []
    for node in nodes:
        got = facets(getattr(getattr(node, "node", node), "text", "") or node.get_content())
        if any(wanted[k] and got[k] and (scope[k] if scope.get(k + "_requested") else wanted[k]).isdisjoint(got[k]) for k in ("indicator", "region", "period", "unit", "scale", "sector")):
            continue
        output.append(node)
    return output


def comparison_issues(dimensions, operation):
    issues = []
    for key in ("indicator", "region", "unit", "kind"):
        if any(len(d[key]) != 1 for d in dimensions):
            issues.append(f"{key}: ausente ou ambíguo")
        if any(d[key] != dimensions[0][key] for d in dimensions[1:]):
            issues.append(f"{key}: incompatível")
    for key in ("scale", "sector", "source", "basis", "coverage"):
        if any(d[key] != dimensions[0][key] for d in dimensions[1:]):
            issues.append(f"{key}: incompatível")
    if any(len(d["period"]) != 1 for d in dimensions):
        issues.append("period: ausente ou ambíguo")
    elif operation in {"difference", "percent_change", "percentage_points"}:
        periods_selected = [next(iter(d["period"])) for d in dimensions]
        granularities = {period_granularity(p) for p in periods_selected}
        if len(set(periods_selected)) != len(periods_selected) or len(granularities) != 1 or "unknown" in granularities:
            issues.append("period: repetido ou granularidade diferente")
        elif periods_selected != sorted(periods_selected):
            issues.append("period: ordem base/final invertida")
    if operation == "sum" and any("taxa" in d["kind"] or "variacao" in d["kind"] or "estoque" in d["kind"] for d in dimensions):
        issues.append("sum: taxa, variação ou estoque não são automaticamente aditivos")
    return sorted(set(issues))


def ontology_report(question, nodes, calculations=(), retrieval_paths=()):
    nodes = list(nodes)
    observations = [obs for node in nodes for obs in node_observations(node)]
    unique = {obs["id"]: obs for obs in observations}
    audits = []
    paths = []
    for node in nodes:
        inner = getattr(node, "node", node)
        raw = (getattr(inner, "metadata", {}) or {}).get("ontology_extraction_audit")
        raw_paths = (getattr(inner, "metadata", {}) or {}).get("graph_paths")
        if raw_paths:
            try:
                paths.append({"node_id": str(getattr(inner, "node_id", "")), "paths": json.loads(raw_paths)})
            except (TypeError, ValueError):
                pass
        if raw:
            try:
                audits.append({"node_id": str(getattr(inner, "node_id", "")), "audit": json.loads(raw)})
            except (TypeError, ValueError):
                audits.append({"node_id": str(getattr(inner, "node_id", "")), "audit": {"error": "audit_format"}})
    paths.extend(retrieval_paths or ())
    paths = list({json.dumps(path, sort_keys=True): path for path in paths}.values())
    from knowledge_analytics import divergence_candidates, comparison_graph
    return {"query": query_constraints(question), "observations": list(unique.values()),
            "divergences": divergence_candidates(list(unique.values())),
            "comparisons": comparison_graph(calculations, list(unique.values())),
            "extraction_audits": audits,
            "retrieval_paths": paths,
            "candidate_count": len(unique), "requires_review": True,
            "method": "declarative_model_and_local_heuristics"}
