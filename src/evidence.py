"""Correspondência contextual conservadora; não é uma prova de implicação semântica."""
import re
import unicodedata
from provenance import source_file, source_page


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


_INDICATORS = {
    "desocupacao": r"desocupacao|desemprego",
    "ocupacao": r"(?<!des)ocupacao|pessoal ocupado|ocupados",
    "pib": r"\bpib\b|produto interno bruto",
    "exportacao": r"exporta\w*", "importacao": r"importa\w*",
    "saldo": r"saldo", "rendimento": r"rendimento|salario|renda",
    "producao": r"producao", "emprego": r"emprego\w*|postos de trabalho",
    "inflacao": r"inflacao|ipca", "participacao": r"participacao",
}
_REGIONS = {
    "sp": r"sao paulo|paulista|\bsp\b",
    "brasil": r"brasil|brasileir\w*|nacional",
    "rmsp": r"rmsp|regiao metropolitana de sao paulo",
    "interior": r"interior", "capital": r"capital|municipio de sao paulo",
}
_UNITS = {
    "percentual": r"%|por cento|percentual",
    "pp": r"p\.\s*p\.|pontos? percentuais?",
    "real": r"r\$|reais", "dolar": r"us\$|dolares",
    "mil": r"\bmil\b|milhares", "milhao": r"milhao|milhoes",
    "bilhao": r"bilhao|bilhoes", "pessoa": r"pessoas|trabalhadores|habitantes",
    "tonelada": r"toneladas?",
}


def facets(text: str) -> dict[str, set[str]]:
    text = fold(text)
    return {
        "indicator": {key for key, pattern in _INDICATORS.items() if re.search(pattern, text)},
        "region": {key for key, pattern in _REGIONS.items() if re.search(pattern, text)},
        "period": set(re.findall(r"\b(?:19|20)\d{2}\b|\b[1-4][ºo°]?\s*trimestre\b|\b(?:janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\b", text)),
        "unit": {key for key, pattern in _UNITS.items() if re.search(pattern, text)},
    }


def claim_spans(text: str):
    """Segmenta sem quebrar separadores decimais/milhares ou abreviações p.p."""
    start = 0
    for match in re.finditer(r"[!?;]\s+|(?<!p)\.(?=\s+[A-ZÀ-Ú]|$)|\n+", text):
        end = match.start() + (1 if text[match.start()] != "\n" else 0)
        raw = text[start:end]
        if raw.strip():
            yield start + len(raw) - len(raw.lstrip()), start + len(raw.rstrip()), raw.strip()
        start = match.end()
    raw = text[start:]
    if raw.strip():
        yield start + len(raw) - len(raw.lstrip()), start + len(raw.rstrip()), raw.strip()


def local_claim(text: str, position: int) -> str:
    for start, end, claim in claim_spans(text):
        if start <= position < end:
            return claim
    return text[max(0, position - 150):position + 150]


def contextual_support(claim: str, excerpt: str) -> tuple[bool, list[str]]:
    wanted, found = facets(claim), facets(excerpt)
    issues = []
    for dimension in ("indicator", "period", "region", "unit"):
        if not wanted[dimension]:
            issues.append(f"{dimension}: não explícito na afirmação")
        elif wanted[dimension] != found[dimension]:
            issues.append(f"{dimension}: sem correspondência no trecho")
    # Facetas coincidentes não bastam se o assunto lexical não coincide.
    words = set(re.findall(r"[a-z]{5,}", fold(claim))) - {"percentual", "paulista", "estado", "registrou", "atingiu", "apresentou"}
    if words and not words.intersection(re.findall(r"[a-z]{5,}", fold(excerpt))):
        issues.append("assunto: sem correspondência lexical")
    return not issues, issues


def build_claim_evidence(answer, nodes, checks, calculations=()):
    """Mantém afirmações sem evidência visíveis; candidatos não são confirmação."""
    records = []
    for start, end, claim in claim_spans(answer):
        numbers = [check for check in checks if start <= check.response_start < end]
        indices = {check.source_index for check in numbers if check.source_index is not None}
        candidates = []
        if not numbers:
            words = set(re.findall(r"[a-z]{5,}", fold(claim)))
            ranked = []
            for index, node in enumerate(nodes):
                overlap = len(words & set(re.findall(r"[a-z]{5,}", fold(node.get_content()))))
                if overlap >= 2:
                    ranked.append((overlap, index))
            indices = {index for _, index in sorted(ranked, reverse=True)[:3]}
        for index in sorted(indices):
            node = nodes[index]
            snippets = [c.source_snippet for c in numbers if c.source_index == index and c.source_snippet]
            candidates.append({
                "source_index": index,
                "node_id": str(getattr(getattr(node, "node", node), "node_id", "")),
                "file": source_file(node), "page": source_page(node),
                "excerpts": snippets or [node.get_content()[:1000]],
            })
        records.append({
            "claim": claim, "start": start, "end": end,
            "status": "context_match" if numbers and all(c.verified for c in numbers) else "requires_review",
            "method": "contextual_heuristic" if numbers else "lexical_candidates",
            "sources": candidates,
            "calculation_candidates": [
                index for index, calculation in enumerate(calculations)
                if str(calculation.get("result", "")).strip()
                and str(calculation["result"]).strip() in claim
            ],
            "numbers": [{"value": c.value, "start": c.response_start, "end": c.response_end,
                         "value_found": c.value_found, "context_match": c.verified,
                         "issues": list(c.context_issues)} for c in numbers],
        })
    return records
