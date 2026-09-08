import asyncio
from pathlib import Path
from types import SimpleNamespace

from domain_skills import DomainSkillRegistry, build_domain_prompt_block
from rag_principal.src.analysis_engine import AnalysisEngine


REPO_ROOT = Path(__file__).resolve().parents[2]


def _registry(monkeypatch):
    monkeypatch.setenv("RAG_MAX_DOMAIN_SKILLS", "2")
    return DomainSkillRegistry(str(REPO_ROOT / "rag_principal"))


def test_registry_discovers_all_domain_skills(monkeypatch):
    registry = _registry(monkeypatch)

    assert set(registry.available_domains()) == {
        "economic_conjuncture",
        "investment_trade",
        "labor_market",
        "sectoral_regional",
    }


def test_registry_matches_accents_and_combines_domains(monkeypatch):
    registry = _registry(monkeypatch)

    matches = registry.match(
        "Compare investimentos anunciados na indústria automotiva paulista."
    )

    assert [skill.domain for skill in matches] == [
        "investment_trade",
        "sectoral_regional",
    ]


def test_registry_prioritizes_labor_and_sector_context(monkeypatch):
    registry = _registry(monkeypatch)

    block = registry.get_prompt_block(
        "Como evoluiu o emprego formal na indústria automotiva?"
    )

    assert "Mercado de Trabalho" in block
    assert "Análise Setorial e Regional" in block
    assert "Não introduzir fatos setoriais externos" in block


def test_registry_combines_investment_with_sector_question(monkeypatch):
    registry = _registry(monkeypatch)

    matches = registry.match(
        "Quais setores receberam mais investimentos anunciados?"
    )

    assert [skill.domain for skill in matches] == [
        "investment_trade",
        "sectoral_regional",
    ]


def test_forced_labor_domain_preserves_legacy_interpreter_signal(monkeypatch):
    registry = _registry(monkeypatch)

    block = build_domain_prompt_block(
        registry,
        "Qual foi o resultado?",
        is_labor_market=True,
    )

    assert "Mercado de Trabalho" in block


def test_unmatched_question_does_not_inject_context(monkeypatch):
    registry = _registry(monkeypatch)

    assert registry.get_prompt_block("Qual documento foi publicado primeiro?") == ""


def test_analysis_engine_injects_registry_context():
    class Retriever:
        def __init__(self, result):
            self.result = result

        def retrieve(self, _question):
            return self.result

    class Registry:
        def is_loaded(self):
            return True

        def get_prompt_block(self, _question, *, forced_domains=()):
            assert forced_domains == ()
            return "\n[DOMÍNIO ECONÔMICO]\n"

    class LLM:
        prompt = ""

        def complete(self, prompt):
            self.prompt = prompt
            return SimpleNamespace(text="Resposta.")

    node = SimpleNamespace(metadata={"source_file": "fonte.pdf", "page": 1})
    llm = LLM()
    engine = AnalysisEngine(
        Retriever([]),
        Retriever(("Indicador: 10", [node])),
        Retriever(None),
        llm,
        domain_skills=Registry(),
    )

    answer, _sources = asyncio.run(
        engine.answer(
            question="Como evoluiu o PIB?",
            sources=["tables"],
            rewritten_query="PIB",
        )
    )

    assert answer == "Resposta."
    assert "[DOMÍNIO ECONÔMICO]" in llm.prompt
