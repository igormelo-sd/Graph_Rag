"""Política compartilhada para o texto visível das respostas RAG."""
from __future__ import annotations

import re

REFUSAL_TEXT = (
    "Os documentos disponíveis não fornecem evidência suficiente para responder "
    "ao ponto solicitado."
)

_SOURCE_REQUEST_PATTERNS = (
    re.compile(
        r"\b(?:qual|quais|liste|mostre|informe|indique)\s+"
        r"(?:(?:foi|foram|[eé]|s[aã]o)\s+)?"
        r"(?:a\s+|as\s+|o\s+|os\s+)?"
        r"(?:fontes?|refer[eê]ncias?|documentos?|arquivos?|pdfs?)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bde onde (?:veio|vem|saiu|foi retirada|foi obtida)\b", re.IGNORECASE),
    re.compile(
        r"\bonde (?:isso|essa informa[cç][aã]o|esse dado|essa afirma[cç][aã]o) "
        r"(?:consta|aparece|est[aá])\b",
        re.IGNORECASE,
    ),
    re.compile(r"\borigem (?:da|dessa) informa[cç][aã]o\b", re.IGNORECASE),
)

_INTERNAL_MARKER_RE = re.compile(
    r"\b(?:"
    r"chunks?|embeddings?|reranking|re-ranking|"
    r"scores? de similaridade|pontua[cç][aã]o de relev[aâ]ncia|"
    r"contexto enviado ao modelo|contexto recuperado|"
    r"documentos? recuperados?|trechos? recuperados?|"
    r"recupera[cç][aã]o (?:de documentos|sem[aâ]ntica|vetorial)|"
    r"sistema RAG|pipeline RAG"
    r")\b",
    re.IGNORECASE,
)

_PARENTHETICAL_SOURCE_RE = re.compile(
    r"\s*\(\s*(?:\*{0,2})?"
    r"(?:fonte|fontes|documento|pdf|arquivo)"
    r"(?:\*{0,2})?\s*(?::|,).*?\)",
    re.IGNORECASE,
)
_PARENTHETICAL_FILE_RE = re.compile(
    r"\s*\([^()\n]*\.(?:pdf|docx?|xlsx?|xls|csv|tsv|txt)"
    r"[^()\n]*\)",
    re.IGNORECASE,
)
_BRACKET_SOURCE_RE = re.compile(
    r"\s*\[(?:\s*\d+(?:\s*[,;]\s*\d+)*\s*|"
    r"\s*(?:fonte|fontes|documento|pdf|arquivo)\b[^\]]*)\]",
    re.IGNORECASE,
)
_ATTRIBUTION_PREFIX_RE = re.compile(
    r"\b(?:segundo|conforme|de acordo com)\s+"
    r"(?:o|a|os|as)?\s*(?:documento|pdf|arquivo|fonte)s?"
    r"(?:\s+[^,;:]+)?\s*[,;:]\s*",
    re.IGNORECASE,
)
_FILE_NAME_RE = re.compile(
    r"(?<![\w.-])[\wÀ-ÿ()_-]+(?:[ _-][\wÀ-ÿ()_-]+)*"
    r"\.(?:pdf|docx?|xlsx?|xls|csv|tsv|txt)\b",
    re.IGNORECASE,
)
_PAGE_REFERENCE_RE = re.compile(
    r"\b(?:p(?:[áa]gina)?\.?|p\./aba|aba)\s*:?\s*"
    r"\d+(?:\s*[-–—]\s*\d+)?\b",
    re.IGNORECASE,
)
_PAGE_ONLY_SENTENCE_RE = re.compile(
    r"(?:^|(?<=[.!?])\s+)"
    r"[^.!?\n]*(?:aparece|consta|encontra-se|est[aá]|veja|consulte)"
    r"\s+(?:na|no|à|a)?\s*(?:p(?:[áa]gina)?\.?|p\./aba|aba)"
    r"\s*:?\s*\d+(?:\s*[-–—]\s*\d+)?[^.!?\n]*[.!?]?",
    re.IGNORECASE,
)
_METADATA_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*{0,2})?"
    r"(?:fonte|fontes|documento|documentos|p[áa]gina|p[áa]ginas|aba|abas)"
    r"(?:\*{0,2})?\s*:?.*$",
    re.IGNORECASE,
)
_SOURCE_SECTION_RE = re.compile(
    r"^\s{0,3}#{1,6}\s*(?:fontes?|refer[eê]ncias?|documentos?)\s*:?\s*$",
    re.IGNORECASE,
)
_SOURCE_BULLET_RE = re.compile(
    r"^\s*[-*]\s+.*(?:\.(?:pdf|docx?|xlsx?|xls|csv|tsv|txt)\b|"
    r"\bp(?:[áa]gina)?\.?\s*:?\s*\d+|\bscore\b).*$",
    re.IGNORECASE,
)
_SOURCE_SENTENCE_RE = re.compile(
    r"(?:^|(?<=[.!?])\s+)(?:\*{0,2})?"
    r"(?:fonte|fontes|documento|documentos|refer[eê]ncia|refer[eê]ncias)"
    r"(?:\*{0,2})?\s*:[^\n]*?"
    r"(?:[.!?](?=\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ])|$)",
    re.IGNORECASE,
)


def asks_for_sources(question: str) -> bool:
    """Detecta pedido explícito por fonte, referência ou documento de origem."""
    return any(pattern.search(question or "") for pattern in _SOURCE_REQUEST_PATTERNS)


def _strip_internal_details(text: str) -> str:
    """Remove frases que expõem mecanismos internos sem afetar análise econômica."""
    parts = re.split(r"(?<=[.!?])(\s+)", text)
    kept: list[str] = []
    for index in range(0, len(parts), 2):
        sentence = parts[index]
        separator = parts[index + 1] if index + 1 < len(parts) else ""
        if not _INTERNAL_MARKER_RE.search(sentence):
            kept.extend((sentence, separator))
    return "".join(kept)


def _strip_source_metadata(text: str) -> str:
    text = _SOURCE_SENTENCE_RE.sub("", text)
    lines = text.splitlines()
    kept: list[str] = []
    in_source_section = False

    for line in lines:
        if _SOURCE_SECTION_RE.match(line):
            in_source_section = True
            continue
        if in_source_section:
            if not line.strip() or _SOURCE_BULLET_RE.match(line):
                continue
            in_source_section = False
        if _METADATA_LINE_RE.match(line) or _SOURCE_BULLET_RE.match(line):
            continue
        kept.append(line)

    cleaned = "\n".join(kept)
    cleaned = _PARENTHETICAL_SOURCE_RE.sub("", cleaned)
    cleaned = _PARENTHETICAL_FILE_RE.sub("", cleaned)
    cleaned = _BRACKET_SOURCE_RE.sub("", cleaned)
    cleaned = _ATTRIBUTION_PREFIX_RE.sub("", cleaned)
    cleaned = _FILE_NAME_RE.sub("", cleaned)
    cleaned = _PAGE_ONLY_SENTENCE_RE.sub("", cleaned)
    cleaned = _PAGE_REFERENCE_RE.sub("", cleaned)
    return cleaned


def sanitize_answer(answer: str, *, question: str = "") -> str:
    """Aplica política de apresentação ao texto que será exibido no chat."""
    cleaned = _strip_internal_details(answer or "")
    if not asks_for_sources(question):
        cleaned = _strip_source_metadata(cleaned)

    cleaned = re.sub(r"\(\s*[,;:-]?\s*\)", "", cleaned)
    cleaned = re.sub(r"[ \t]+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n[ \t]+", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip(" \t\n,;:-")
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned or REFUSAL_TEXT
