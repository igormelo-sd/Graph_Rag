"""
Validação numérica de respostas RAG.

Pipeline:
    resposta do LLM → extrai números → compara com chunks de origem → relatório
"""
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

# ── Regex para números em PT-BR ───────────────────────────────────────────────
# Captura: 1.234,56 | 1.234 | 4,2 | 42 | com % opcional
# Exclui inteiros de 1 dígito (muito comuns, sem valor estatístico)
_NUM_RE = re.compile(
    r"(?<!\w)"
    r"([-−]?"
    r"(?:"
    r"\d{1,3}(?:\.\d{3})+(?:,\d+)?"   # 1.234 ou 1.234,56
    r"|\d+,\d+"                         # 4,2
    r"|\d{2,}"                          # inteiro ≥ 2 dígitos
    r")"
    r"(?:\s*%)?)"
    r"(?!\w)"
)

_NUM_ATOM = (
    r"[-−]?(?:\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+,\d+|\d{2,})(?:\s*%)?"
)
_EQUATION_RE = re.compile(
    rf"({_NUM_ATOM})\s*([+\-−×x*/÷])\s*({_NUM_ATOM})\s*=\s*({_NUM_ATOM})"
)

# ── Dataclass de resultado ────────────────────────────────────────────────────

@dataclass
class NumberCheck:
    value: str                          # como aparece na resposta
    verified: bool
    source_snippet: Optional[str] = None  # trecho onde foi encontrado
    response_snippet: Optional[str] = None  # contexto na resposta do LLM
    derived: bool = False
    response_start: Optional[int] = None
    response_end: Optional[int] = None
    source_index: Optional[int] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize(s: str) -> str:
    """Converte número PT-BR para string numérica comparável."""
    s = s.strip().rstrip("%").strip().replace("−", "-")
    if "," in s and "." in s:
        # 1.234,56 → 1234.56
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        # 4,2 → 4.2
        s = s.replace(",", ".")
    return s


def _normalized_numbers(text: str) -> set[str]:
    return {_normalize(match.group(1)) for match in _NUM_RE.finditer(text)}


def _derived_results(response_text: str, source_texts: list[str]) -> set[str]:
    """Aceita apenas resultados de equações explícitas cujos operandos estão nas fontes."""
    source_numbers = set().union(*(_normalized_numbers(text) for text in source_texts))
    derived: set[str] = set()
    for match in _EQUATION_RE.finditer(response_text):
        left_raw, operator, right_raw, result_raw = match.groups()
        if _normalize(left_raw) not in source_numbers or _normalize(right_raw) not in source_numbers:
            continue
        try:
            left = Decimal(_normalize(left_raw))
            right = Decimal(_normalize(right_raw))
            expected = Decimal(_normalize(result_raw))
            if operator == "+":
                calculated = left + right
            elif operator in {"-", "−"}:
                calculated = left - right
            elif operator in {"×", "x", "*"}:
                calculated = left * right
            elif right != 0:
                calculated = left / right
            else:
                continue
        except (InvalidOperation, ZeroDivisionError):
            continue
        decimals = max(0, -expected.as_tuple().exponent)
        tolerance = Decimal("0.5") * (Decimal(10) ** -decimals)
        if abs(calculated - expected) <= tolerance:
            derived.add(_normalize(result_raw))
    return derived


def _find_snippet(needle: str, haystack: str, ctx: int = 60) -> str:
    idx = haystack.find(needle)
    if idx == -1:
        return ""
    start = max(0, idx - ctx)
    end = min(len(haystack), idx + len(needle) + ctx)
    return "…" + haystack[start:end].strip() + "…"


def _source_snippet(needle: str, source_text: str, source_node) -> str:
    """Preserva uma linha tabular completa; usa contexto narrativo nos demais casos."""
    metadata = getattr(source_node, "metadata", {}) or {}
    if metadata.get("type") == "table":
        blocks = re.split(r"\n\s*---\s*\n", source_text)
        for block in blocks:
            if needle not in block:
                continue
            lines = [
                line.strip()
                for line in block.splitlines()
                if line.strip() and not line.strip().lower().startswith("fonte:")
            ]
            return "\n".join(lines)[:1_000]
    return _find_snippet(needle, source_text, ctx=140)


# ── Validação principal ───────────────────────────────────────────────────────

def validate_numbers(response_text: str, source_nodes) -> list[NumberCheck]:
    """
    Extrai todos os números da resposta e verifica se existem nos chunks de origem.
    Tenta primeiro match verbatim, depois match normalizado (diferenças de formatação).
    """
    source_texts = [n.get_content() for n in source_nodes]
    derived_results = _derived_results(response_text, source_texts)

    seen: set[str] = set()
    results: list[NumberCheck] = []

    for m in _NUM_RE.finditer(response_text):
        raw = m.group(1).strip()
        if raw in seen:
            continue
        seen.add(raw)

        resp_snippet = _find_snippet(raw, response_text, ctx=140)
        response_position = {
            "response_start": m.start(1),
            "response_end": m.end(1),
        }

        # 1. Match verbatim
        verbatim_source = next(
            (
                (source_index, node_text)
                for source_index, node_text in enumerate(source_texts)
                if raw in node_text
            ),
            None,
        )
        if verbatim_source is not None:
            source_index, node_text = verbatim_source
            results.append(NumberCheck(
                value=raw,
                verified=True,
                source_snippet=_source_snippet(
                    raw, node_text, source_nodes[source_index]
                ),
                response_snippet=resp_snippet,
                source_index=source_index,
                **response_position,
            ))
            continue

        # 2. Match normalizado (trata diferenças de formatação PT-BR vs EN)
        norm = _normalize(raw)
        found = False
        for source_index, node_text in enumerate(source_texts):
            for cm in _NUM_RE.finditer(node_text):
                if _normalize(cm.group(1).strip()) == norm:
                    results.append(NumberCheck(
                        value=raw,
                        verified=True,
                        source_snippet=_source_snippet(
                            cm.group(1), node_text, source_nodes[source_index]
                        ),
                        response_snippet=resp_snippet,
                        source_index=source_index,
                        **response_position,
                    ))
                    found = True
                    break
            if found:
                break

        if not found and norm in derived_results:
            results.append(NumberCheck(
                value=raw,
                verified=True,
                response_snippet=resp_snippet,
                derived=True,
                **response_position,
            ))
        elif not found:
            results.append(NumberCheck(
                value=raw,
                verified=False,
                response_snippet=resp_snippet,
                **response_position,
            ))

    return results


def format_validation_report(checks: list[NumberCheck]) -> str:
    """Formata o relatório de validação para exibição no console."""
    if not checks:
        return "  Nenhum número encontrado na resposta."

    verified = [c for c in checks if c.verified]
    unverified = [c for c in checks if not c.verified]

    lines = [f"  Verificados nos documentos: {len(verified)}/{len(checks)}"]

    if unverified:
        lines.append("  ⚠️  Não encontrados nos documentos originais:")
        for c in unverified:
            lines.append(f"    • {c.value}")
            if c.response_snippet:
                lines.append(f"      Contexto na resposta: {c.response_snippet}")
    else:
        lines.append("  ✅ Todos os números foram verificados nos documentos.")

    return "\n".join(lines)
