import pytest
from pydantic import ValidationError
from types import SimpleNamespace

from api_models import SourceInfo
from metrics import (
    record_estimated_usage,
    record_http,
    record_reported_usage,
    render_prometheus,
    snapshot,
)


def test_metricas_expoem_latencia_tokens_e_custo(monkeypatch):
    service = "test_metrics_unique"
    monkeypatch.setenv("RAG_INPUT_COST_PER_MILLION_USD", "1")
    monkeypatch.setenv("RAG_OUTPUT_COST_PER_MILLION_USD", "2")
    record_http(service, "/query", 200, 12.5)
    usage = record_estimated_usage(service, "a" * 400, "b" * 200)
    record_reported_usage(
        service,
        SimpleNamespace(usage=SimpleNamespace(prompt_tokens=120, completion_tokens=60)),
    )

    assert usage["estimated_input_tokens"] == 100
    assert usage["estimated_output_tokens"] == 50
    assert usage["estimated_cost_usd"] == pytest.approx(0.0002)
    assert snapshot()["http"][(service, "/query")]["count"] == 1
    assert snapshot()["usage"][service]["reported_input_tokens"] == 120

    output = render_prometheus()
    assert f'service="{service}"' in output
    assert "rag_http_request_latency_ms_sum" in output
    assert "rag_estimated_cost_usd_total" in output
    assert "rag_reported_cost_usd_total" in output


def test_schema_rejeita_score_fora_do_contrato():
    with pytest.raises(ValidationError):
        SourceInfo(file="a.pdf", score=1.5)
