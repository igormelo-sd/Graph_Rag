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


def point_comparison(question: str) -> bool:
    """Uma taxa publicada em um recorte não pede uma série ou gráfico novo."""
    text = _fold(question)
    point = re.search(r"\b(?:qual|quanto)\b.*\b(?:variacao|crescimento|taxa)\b", text)
    period = re.search(r"\b(?:19|20)\d{2}\b", text)
    sequence = re.search(r"\b(?:evolucao|trajetoria|tendencia|serie|series|grafico|calcule|calcular|calculo)\b|ao longo|a partir|com base", text)
    return bool(point and period and not sequence)


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


def services_growth_clarification(question: str) -> dict | None:
    """Uma taxa de serviços sem período nem recorte não define uma consulta."""
    text = _fold(question)
    asks_rate = re.search(r"\b(?:qual|quanto|informe|mostre)\b", text)
    growth = re.search(r"\b(?:crescimento|variacao|taxa|variou|cresceu)\b", text)
    services = re.search(r"\bservicos\b", text)
    period = re.search(r"\b(?:19|20)\d{2}\b|\b(?:ontem|hoje|ultimo|ultima|recente)\b", text)
    concept = re.search(r"\b(?:significa|conceito|definicao|metodologia|fonte|fontes)\b", text)
    if asks_rate and growth and services and not period and not concept:
        return {
            "required": True, "dimension": "statistical_scope",
            "reason": "missing_services_comparison",
            "question": "De qual território, período e segmento dos serviços você quer o crescimento? Informe também a base de comparação, por exemplo, mês anterior com ajuste sazonal ou mesmo mês do ano anterior.",
            "options": [],
        }
    return None
