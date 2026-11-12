"""Testes das explicações estruturadas usadas nos popups numéricos."""
import asyncio
import json
from types import SimpleNamespace

from api_models import NumericCitationInfo
from popup_explanations import generate_popup_explanations


class _Completions:
    def __init__(self, payload):
        self.payload = payload
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(self.payload, ensure_ascii=False)
                    )
                )
            ],
            usage=None,
        )


def _citation(value: str, claim: str, snippet: str) -> NumericCitationInfo:
    return NumericCitationInfo(
        value=value,
        start=0,
        end=len(value),
        source_index=0,
        file="boletim.pdf",
        score=0.9,
        page=2,
        snippet=snippet,
        claim=claim,
    )


def test_gera_em_lote_e_rejeita_numero_inventado(monkeypatch):
    monkeypatch.setenv("RAG_POPUP_EXPLANATIONS", "1")
    completions = _Completions(
        {
            "explanations": [
                {"index": 0, "text": "A taxa observada no período foi de 7,9%."},
                {"index": 1, "text": "O total chegou a 10 em 2025."},
            ]
        }
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    citations = [
        _citation("7,9%", "A taxa foi 7,9%.", "Taxa no período: 7,9%."),
        _citation("10", "O total foi 10.", "Total em 2024: 10."),
    ]

    result = asyncio.run(
        generate_popup_explanations(
            citations,
            client=client,
            model="modelo-teste-validacao",
        )
    )

    assert result == {0: "A taxa observada no período foi de 7,9%."}
    assert completions.kwargs["model"] == "modelo-teste-validacao"
    assert completions.kwargs["response_format"]["type"] == "json_schema"
    schema = completions.kwargs["response_format"]["json_schema"]["schema"]
    serialized_schema = json.dumps(schema)
    assert "minLength" not in serialized_schema
    assert "maxLength" not in serialized_schema
    assert "minimum" not in serialized_schema
    sent = json.loads(completions.kwargs["messages"][1]["content"])
    assert len(sent["citations"]) == 2


def test_falha_da_llm_mantem_fallback(monkeypatch):
    monkeypatch.setenv("RAG_POPUP_EXPLANATIONS", "1")
    completions = _Completions({"formato": "inesperado"})
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )

    result = asyncio.run(
        generate_popup_explanations(
            [_citation("12,5%", "A taxa foi 12,5%.", "Taxa: 12,5%.")],
            client=client,
            model="modelo-teste-fallback",
        )
    )

    assert result == {}
