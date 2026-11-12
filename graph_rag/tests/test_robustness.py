import asyncio
from types import SimpleNamespace

from analysis_engine import AnalysisEngine
from query_service import execute_engine_query


class _Retriever:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def retrieve(self, _query):
        if self.error:
            raise self.error
        return self.result


class _LLM:
    def complete(self, _prompt):
        return SimpleNamespace(text="Resposta parcial baseada na tabela.")


def test_analysis_engine_tolera_falha_parcial_de_retriever():
    node = SimpleNamespace(get_content=lambda: "Fonte: tabela.csv\nValor: 10")
    engine = AnalysisEngine(
        _Retriever(error=RuntimeError("texto indisponível")),
        _Retriever(result=("Valor: 10", [node])),
        _Retriever(result=None),
        _LLM(),
    )
    answer, sources = asyncio.run(engine.answer(
        question="Qual o valor?",
        sources=["text", "tables", "timeseries"],
        rewritten_query="valor",
    ))
    assert answer == "Resposta parcial baseada na tabela."
    assert sources == [node]


def test_servico_compartilhado_preserva_contrato_http(monkeypatch):
    node = SimpleNamespace(
        metadata={"source_file": "boletim.pdf", "page": 2},
        score=0.9,
        get_content=lambda: "A desocupação foi 7,9% no estado de São Paulo em 2023.",
    )

    class Engine:
        async def answer(self, **_kwargs):
            return "A desocupação foi 7,9% no estado de São Paulo em 2023 (Fonte: boletim.pdf, p. 2).", [node]

    def interpreter(question, _llm):
        return {"sources": ["text"], "rewritten_query": question, "is_labor_market": False}

    async def popup_explanations(_citations):
        return {0: "A taxa informada foi de 7,9%."}

    monkeypatch.setattr(
        "query_service.generate_popup_explanations",
        popup_explanations,
    )
    response, diagnostics = asyncio.run(execute_engine_query(
        question="Qual foi a taxa?",
        engine=Engine(),
        interp_llm=object(),
        interpreter=interpreter,
        rag_type="test",
        rag_label="Test RAG",
    ))
    assert response.sources[0].file == "boletim.pdf"
    assert response.sources[0].page == 2
    assert response.sources[0].excerpt == "A desocupação foi 7,9% no estado de São Paulo em 2023."
    assert response.numeric_citations[0].value == "7,9%"
    assert response.numeric_citations[0].file == "boletim.pdf"
    assert response.numeric_citations[0].page == 2
    assert response.numeric_citations[0].snippet
    assert "A desocupação foi 7,9%" in response.numeric_citations[0].claim
    assert response.numeric_citations[0].explanation == "A taxa informada foi de 7,9%."
    assert response.answer == "A desocupação foi 7,9% no estado de São Paulo em 2023."
    assert response.validation.verified == 2
    assert diagnostics.chunks == 1



def test_resposta_vazia_do_modelo_nao_vira_ausencia_de_dados(monkeypatch):
    from rag_app.model_output import EmptyModelResponse
    import pytest
    monkeypatch.setenv("RAG_ONTOLOGY_ENABLE", "0")
    source = SimpleNamespace(metadata={"source_file": "boletim.pdf", "page": 1},
                             get_content=lambda: "A indústria paulista recuou em dezembro de 2025.")
    engine = AnalysisEngine(
        _Retriever(result=[source]), _Retriever(result=None), _Retriever(result=None),
        SimpleNamespace(complete=lambda _: SimpleNamespace(text="   ")),
    )
    with pytest.raises(EmptyModelResponse, match="resposta vazia"):
        asyncio.run(engine.answer(question="Me fale sobre a economia do Estado de São Paulo",
                                  sources=["text"], rewritten_query="economia paulista"))



def test_api_reports_empty_provider_output_as_502(monkeypatch):
    import os
    import pytest
    from fastapi import HTTPException
    from rag_app.model_output import EmptyModelResponse
    # Importar a API não deve mudar o ambiente dos outros testes.
    monkeypatch.setattr(os, "environ", dict(os.environ))
    import api
    monkeypatch.setattr(api, "_engine", object())
    monkeypatch.setattr(api, "_interp_llm", object())
    async def empty(**kwargs):
        raise EmptyModelResponse("O modelo retornou uma resposta vazia.")
    monkeypatch.setattr(api, "execute_engine_query", empty)
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.query(api.QueryRequest(question="Economia paulista")))
    assert error.value.status_code == 502
    assert "resposta vazia" in error.value.detail
