"""Descoberta e roteamento de skills de domínio para prompts RAG."""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from logger import get_logger
from runtime import bounded_int

log = get_logger(__name__)

_CONTEXT_RE = re.compile(
    r"<!--\s*rag-context:start\s*-->(.*?)"
    r"<!--\s*rag-context:end\s*-->",
    re.DOTALL | re.IGNORECASE,
)
_ROUTING_LOCATIONS = (
    Path("references") / "rag-routing.json",
    Path("resources") / "rag-routing.json",
)


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(
        character for character in decomposed
        if not unicodedata.combining(character)
    )
    return re.sub(r"\s+", " ", without_marks).strip()


def _contains(normalized_question: str, normalized_keyword: str) -> bool:
    pattern = rf"(?<!\w){re.escape(normalized_keyword)}(?!\w)"
    return re.search(pattern, normalized_question) is not None


@dataclass(frozen=True)
class DomainSkill:
    domain: str
    label: str
    priority: int
    keywords: tuple[str, ...]
    context: str
    path: Path

    def score(self, normalized_question: str) -> int:
        score = 0
        for keyword in self.keywords:
            normalized_keyword = _normalize(keyword)
            if _contains(normalized_question, normalized_keyword):
                score += 1 + normalized_keyword.count(" ")
        return score


class DomainSkillRegistry:
    """Carrega skills marcadas e seleciona até N domínios por pergunta."""

    def __init__(self, base_dir: str):
        self._skills = self._load_skills(self._resolve_root(base_dir))

    @staticmethod
    def _resolve_root(base_dir: str) -> Path:
        base = Path(base_dir).resolve()
        candidates = (
            base / ".agents" / "skills",
            base.parent / ".agents" / "skills",
            base.parent.parent / ".agents" / "skills",
        )
        return next((path for path in candidates if path.is_dir()), candidates[0])

    @staticmethod
    def _routing_path(skill_dir: Path) -> Path | None:
        return next(
            (
                skill_dir / relative
                for relative in _ROUTING_LOCATIONS
                if (skill_dir / relative).is_file()
            ),
            None,
        )

    def _load_skills(self, root: Path) -> tuple[DomainSkill, ...]:
        if not root.is_dir():
            return ()

        loaded: list[DomainSkill] = []
        for skill_dir in sorted(path for path in root.iterdir() if path.is_dir()):
            skill_path = skill_dir / "SKILL.md"
            routing_path = self._routing_path(skill_dir)
            if not skill_path.is_file() or routing_path is None:
                continue
            try:
                routing = json.loads(routing_path.read_text(encoding="utf-8"))
                content = skill_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                log.warning("Skill de domínio inválida em %s: %s", skill_dir, exc)
                continue

            match = _CONTEXT_RE.search(content)
            domain = routing.get("domain")
            label = routing.get("label")
            keywords = routing.get("keywords")
            try:
                priority = int(routing.get("priority", 0))
            except (TypeError, ValueError):
                priority = 0
            if (
                not match
                or not isinstance(domain, str)
                or not domain.strip()
                or not isinstance(label, str)
                or not label.strip()
                or not isinstance(keywords, list)
                or not all(isinstance(keyword, str) and keyword.strip() for keyword in keywords)
            ):
                log.warning("Skill de domínio incompleta: %s", skill_dir)
                continue

            loaded.append(
                DomainSkill(
                    domain=domain.strip(),
                    label=label.strip(),
                    priority=priority,
                    keywords=tuple(keywords),
                    context=match.group(1).strip(),
                    path=skill_path,
                )
            )

        if loaded:
            log.info(
                "Skills de domínio carregadas: %s",
                ", ".join(skill.domain for skill in loaded),
            )
        return tuple(loaded)

    def is_loaded(self) -> bool:
        return bool(self._skills)

    def available_domains(self) -> tuple[str, ...]:
        return tuple(skill.domain for skill in self._skills)

    def match(
        self,
        question: str,
        *,
        forced_domains: tuple[str, ...] = (),
    ) -> list[DomainSkill]:
        normalized_question = _normalize(question)
        forced = set(forced_domains)
        ranked = []
        for skill in self._skills:
            score = skill.score(normalized_question)
            if score or skill.domain in forced:
                ranked.append(
                    (
                        skill.domain not in forced,
                        -score,
                        -skill.priority,
                        skill.domain,
                        skill,
                    )
                )
        ranked.sort()
        limit = bounded_int("RAG_MAX_DOMAIN_SKILLS", 2, 1, 4)
        return [item[-1] for item in ranked[:limit]]

    def get_prompt_block(
        self,
        question: str,
        *,
        forced_domains: tuple[str, ...] = (),
    ) -> str:
        matches = self.match(question, forced_domains=forced_domains)
        if not matches:
            return ""

        log.info(
            "Skills aplicadas à consulta: %s",
            ", ".join(skill.domain for skill in matches),
        )
        blocks = []
        for skill in matches:
            blocks.append(
                f"[Conhecimento Especializado — {skill.label}]\n"
                "Aplicar estas regras somente para interpretar o contexto "
                "documental recuperado.\n"
                f"{skill.context}\n"
                "[Fim do Conhecimento Especializado]"
            )
        return "\n\n" + "\n\n".join(blocks) + "\n"


def build_domain_prompt_block(
    registry,
    question: str,
    *,
    is_labor_market: bool = False,
    legacy_labor_skill=None,
) -> str:
    """Monta bloco genérico, mantendo compatibilidade com a skill antiga."""
    if registry is not None and registry.is_loaded():
        forced = ("labor_market",) if is_labor_market else ()
        return registry.get_prompt_block(question, forced_domains=forced)

    if (
        is_labor_market
        and legacy_labor_skill is not None
        and legacy_labor_skill.is_loaded()
    ):
        return (
            "\n\n[Conhecimento Especializado — Mercado de Trabalho]\n"
            f"{legacy_labor_skill.get_context()}\n"
            "[Fim do Conhecimento Especializado]\n"
        )
    return ""
