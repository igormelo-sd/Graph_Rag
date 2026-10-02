"""
Validação numérica de respostas RAG.

Pipeline:
    resposta do LLM → extrai números → compara com chunks de origem → relatório
"""
import re
from dataclasses import dataclass
from typing import Optional
from evidence import contextual_support, local_claim

# ── Regex para números em PT-BR ───────────────────────────────────────────────
# Captura: 1.234,56 | 1.234 | 4,2 | 42 | com % opcional
# Inclui inteiros de um dígito e verifica cada ocorrência contextual.
_NUM_RE = re.compile(
    r"(?<!\w)"
    r"([-−]?"
    r"(?:"
    r"\d{1,3}(?:\.\d{3})+(?:,\d+)?"   # 1.234 ou 1.234,56
    r"|\d+,\d+"                         # 4,2
    r"|\d+"                             # inclui valores de um dígito
    r")"
    r"(?:\s*%)?)"
    r"(?!\w)"
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
    value_found: bool = False
    context_issues: tuple[str, ...] = ()


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
    elif re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", s):
        s = s.replace(".", "")
    return s


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
    """Valida cada ocorrência; coincidência numérica isolada não é confirmação."""
    results = []
    source_texts = [n.get_content() for n in source_nodes]
    for match in _NUM_RE.finditer(response_text):
        raw = match.group(1).strip()
        claim = local_claim(response_text, match.start(1))
        candidates = []
        for index, text in enumerate(source_texts):
            for source_match in _NUM_RE.finditer(text):
                if _normalize(source_match.group(1)) != _normalize(raw):
                    continue
                excerpt = local_claim(text, source_match.start(1))
                supported, issues = contextual_support(claim, excerpt)
                if ('%' in raw) != ('%' in source_match.group(1)):
                    supported = False
                    issues.append('unit: percentual e valor absoluto divergentes')
                observations = list(_NUM_RE.finditer(excerpt))
                non_years = [m for m in observations if not re.fullmatch(r'(19|20)\d{2}', m.group(1))]
                if len(non_years) > 1:
                    supported = False
                    issues.append('associação: múltiplos valores no mesmo trecho')
                candidates.append((supported, issues, index, excerpt))
        best = min(candidates, key=lambda item: (not item[0], len(item[1]))) if candidates else None
        results.append(NumberCheck(
            value=raw, verified=bool(best and best[0]),
            source_snippet=best[3][:1000] if best else None,
            response_snippet=claim[:1000],
            response_start=match.start(1), response_end=match.end(1),
            source_index=best[2] if best else None,
            value_found=bool(best),
            context_issues=tuple(best[1] if best else ['valor ausente das fontes']),
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
        lines.append("  ⚠️  Sem confirmação contextual suficiente:")
        for c in unverified:
            lines.append(f"    • {c.value}")
            if c.response_snippet:
                lines.append(f"      Contexto na resposta: {c.response_snippet}")
    else:
        lines.append("  Correspondência contextual heurística encontrada para todos os números.")

    return "\n".join(lines)
