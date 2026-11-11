"""
Labor Market Skill — carrega a skill especializada de mercado de trabalho
e expõe um contexto compacto para enriquecer o prompt de síntese do
Analysis Engine quando a query for sobre emprego, desemprego, informalidade, etc.

O conteúdo é extraído de:
    .agents/skills/labor_market_analysis/SKILL.md
"""
import os
import re

# ── Keywords para detecção de queries de mercado de trabalho ─────────────────

_LABOR_MARKET_KEYWORDS = {
    "emprego", "desemprego", "desocupação", "desocupado", "ocupação",
    "ocupado", "trabalhador", "trabalho", "mercado de trabalho",
    "informalidade", "informal", "formal", "carteira assinada", "clt",
    "caged", "rais", "pnadc", "pnad contínua", "ped",
    "remuneração", "salário", "renda do trabalho",
    "admissão", "desligamento", "saldo de empregos", "vagas",
    "taxa de desocupação", "taxa de emprego", "taxa de informalidade",
    "pea", "população economicamente ativa", "subocupação", "subutilização",
    "rotatividade", "turnover", "demissão", "contratação",
    "setor formal", "setor informal", "emprego formal", "emprego informal",
}

# ── Seções do SKILL.md que são úteis no prompt de síntese ────────────────────

_SECTION_RE = {
    "glossary":  re.compile(
        r"### Glossário de Indicadores-Chave\n(.*?)(?=\n---|\n##|\Z)", re.DOTALL
    ),
    "checklist": re.compile(
        r"### Checklist de Interpretação\n(.*?)(?=\n---|\n###|\Z)", re.DOTALL
    ),
}


def is_labor_market_query(question: str) -> bool:
    """Retorna True se a pergunta for sobre mercado de trabalho."""
    q = question.lower()
    return any(kw in q for kw in _LABOR_MARKET_KEYWORDS)


class LaborMarketSkill:
    """
    Carrega a skill de mercado de trabalho e expõe contexto compacto
    (glossário de indicadores + checklist de interpretação).
    """

    def __init__(self, base_dir: str):
        skill_path = os.path.join(
            base_dir,
            ".agents", "skills", "labor_market_analysis", "SKILL.md",
        )
        self._context = self._load(skill_path)

    def _load(self, path: str) -> str:
        if not os.path.exists(path):
            return ""

        with open(path, encoding="utf-8") as f:
            content = f.read()

        sections = []
        for name, pattern in _SECTION_RE.items():
            match = pattern.search(content)
            if match:
                sections.append(match.group(0).strip())

        return "\n\n".join(sections) if sections else ""

    def get_context(self) -> str:
        """Retorna o contexto compacto da skill para injeção no prompt."""
        return self._context

    def is_loaded(self) -> bool:
        return bool(self._context)
