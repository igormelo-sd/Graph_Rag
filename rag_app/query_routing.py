"""Regras mínimas de roteamento para não perder consultas numéricas em tabelas."""
import re
import unicodedata


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower())
                   if not unicodedata.combining(c))


def _pib_value_question(question: str) -> bool:
    text = _fold(question)
    indicator = re.search(r"\bpib\b|produto interno bruto", text)
    concept = re.search(
        r"\bo que (?:e|significa)\b|\b(?:definicao|conceito|metodologia|como|por que|"
        r"fonte|fontes|formula|ponderacao|otica|ano.base|periodo de referencia|unidade de medida)\b", text)
    point = re.search(r"\b(?:qual|quanto|valor|informe|mostre|consulte)\b", text)
    return bool(indicator and point and not concept)


def minimum_sources(question: str, sources=()) -> list[str]:
    """Acrescenta tabelas a pedidos de PIB; mantém a seleção das outras fontes."""
    selected = list(dict.fromkeys(sources))
    if "text" not in selected:
        selected.insert(0, "text")
    if _pib_value_question(question) and "tables" not in selected:
        selected.append("tables")
    return selected


def period_clarification(question: str) -> dict | None:
    text = _fold(question)
    if not _pib_value_question(question):
        return None
    if re.search(r"\b(?:19|20)\d{2}\b|mais recente|ultimo (?:ano|periodo|dado)|ultima divulgacao", text):
        return None
    return {
        "required": True, "dimension": "period", "reason": "missing_reference_period",
        "question": "De qual ano ou período você quer o PIB? Informe também o recorte territorial, por exemplo: município de Campinas em 2020 ou Região Administrativa de Campinas em 2025.",
        "options": [],
    }
