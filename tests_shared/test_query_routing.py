import pytest
from rag_app.query_routing import minimum_sources, period_clarification


def test_pib_value_always_consults_tables():
    assert minimum_sources("Qual é o PIB do município de Campinas em 2020?", ["text"]) == ["text", "tables"]
    assert minimum_sources("Quanto foi o Produto Interno Bruto municipal em 2020?", []) == ["text", "tables"]


def test_missing_year_does_not_become_absence_of_data():
    result = period_clarification("Qual é o pib de campinas?")
    assert result["required"] and result["dimension"] == "period"


@pytest.mark.parametrize("question", [
    "Qual é o PIB do município de Campinas em 2020?",
    "Qual é o PIB mais recente do município de Campinas?",
    "O que é PIB?", "Qual é a metodologia de cálculo do PIB?",
    "Qual período de referência é usado no índice de PIB?",
    "Quais são as fontes usadas no PIB mensal?",
    "Me fale sobre a economia de São Paulo",
])
def test_definitions_and_explicit_period_do_not_require_a_year(question):
    assert period_clarification(question) is None


def test_does_not_duplicate_sources_or_remove_timeseries():
    assert minimum_sources("Qual PIB em 2020?", ["tables", "timeseries", "tables"]) == ["text", "tables", "timeseries"]


def test_console_shows_clarification_without_retrieval(monkeypatch, capsys, tmp_path):
    import sys
    from types import SimpleNamespace
    from rag_app.console import run_cli

    def forbidden(**kwargs):
        raise AssertionError("Não deve buscar evidências antes do esclarecimento")

    engine = SimpleNamespace(answer=forbidden)
    monkeypatch.setitem(sys.modules, "startup", SimpleNamespace(initialize=lambda *a, **k: (engine, None)))
    monkeypatch.setitem(sys.modules, "query_interpreter", SimpleNamespace(
        interpret_query=lambda question, _: {"sources": [], "clarification": period_clarification(question)}))
    monkeypatch.setitem(sys.modules, "numerical_validator", SimpleNamespace(
        validate_numbers=forbidden, format_validation_report=forbidden))
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    answers = iter(["Qual é o pib de campinas?", "sair"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    run_cli(tmp_path)
    output = capsys.readouterr().out
    assert "De qual ano ou período" in output
    assert "Buscando e analisando" not in output
