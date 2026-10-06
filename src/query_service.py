"""Fluxo HTTP comum das engines, sem acoplar suas estratégias de recuperação."""
from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass

from answer_policy import sanitize_answer
from api_models import (
    CitationValidationInfo,
    NumericCitationInfo,
    QueryResponse,
    SourceInfo,
    ValidationInfo,
)
from citation_validator import validate_citations
from logger import get_logger
from numerical_validator import validate_numbers
from metrics import record_estimated_usage
from popup_explanations import generate_popup_explanations
from provenance import relevance_score, source_file, source_page
from runtime import request_timeout_seconds
from load_control import request_slot
from evidence import build_claim_evidence
from query_usage import usage_scope
from domain_ontology import ontology_report

_SOURCE_EXCERPT_MAX_CHARS = 4_000
log = get_logger(__name__)


def _source_excerpt(node) -> str:
    """Serializa o trecho recuperado sem deixar a resposta HTTP crescer sem limite."""
    content = str(node.get_content() or "").strip()
    if len(content) <= _SOURCE_EXCERPT_MAX_CHARS:
        return content
    marker = "\n\n[Trecho truncado]"
    return content[: _SOURCE_EXCERPT_MAX_CHARS - len(marker)].rstrip() + marker


@dataclass(frozen=True)
class QueryDiagnostics:
    sources: list[str]
    chunks: int
    verified: int
    total: int
    unverified: list[str]
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_usd: float


async def execute_engine_query(
    **kwargs,
) -> tuple[QueryResponse, QueryDiagnostics]:
    """Aplica o prazo à interpretação, busca, síntese e pós-processamento."""
    async with request_slot():
        with usage_scope() as usage:
            response, diagnostics = await asyncio.wait_for(
                _execute_engine_query(**kwargs), timeout=request_timeout_seconds()
            )
            response.usage = usage.snapshot()
            return response, diagnostics


async def _execute_engine_query(
    *,
    question: str,
    engine,
    interp_llm,
    interpreter,
    rag_type: str,
    rag_label: str,
) -> tuple[QueryResponse, QueryDiagnostics]:
    """Interpreta, executa, valida e serializa uma consulta de engine."""
    interp = await asyncio.to_thread(interpreter, question, interp_llm)
    kwargs = dict(
        question=question, sources=interp["sources"],
        rewritten_query=interp["rewritten_query"],
        is_labor_market=interp.get("is_labor_market", False),
    )
    parameters = inspect.signature(engine.answer).parameters
    if "rewritten_queries" in parameters or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values()
    ):
        kwargs["rewritten_queries"] = interp.get("rewritten_queries")
    result = await engine.answer(**kwargs)
    answer, source_nodes = result
    answer = sanitize_answer(answer, question=question)
    timeseries_chart = getattr(result, "chart", None)
    checks = await asyncio.to_thread(validate_numbers, answer, source_nodes)
    unverified = [check.value for check in checks if not check.verified]
    verified = len(checks) - len(unverified)
    citation_checks = await asyncio.to_thread(validate_citations, answer, source_nodes)
    unverified_citations = [
        check.citation for check in citation_checks if not check.verified
    ]
    usage = record_estimated_usage(
        rag_type,
        question + "\n" + "\n".join(node.get_content() for node in source_nodes),
        answer,
    )
    numeric_citations = [
        NumericCitationInfo(
            value=check.value,
            start=check.response_start,
            end=check.response_end,
            source_index=check.source_index,
            file=source_file(source_nodes[check.source_index]),
            score=relevance_score(source_nodes[check.source_index]),
            page=source_page(source_nodes[check.source_index]),
            snippet=check.source_snippet or "",
            content_type=str(
                (
                    getattr(source_nodes[check.source_index], "metadata", {})
                    or {}
                ).get("type")
                or "text"
            ),
            claim=check.response_snippet or "",
        )
        for check in checks
        if (
            check.verified
            and not check.derived
            and check.response_start is not None
            and check.response_end is not None
            and check.source_index is not None
        )
    ]
    try:
        explanations = await generate_popup_explanations(numeric_citations)
    except Exception as exc:
        log.warning("Falha inesperada nas explicações de popup; usando fallback: %s", exc)
        explanations = {}
    for index, explanation in explanations.items():
        if 0 <= index < len(numeric_citations):
            numeric_citations[index].explanation = explanation

    # Proveniência: chunk_id/total para inspector (RAG_CHUNK_PROVENANCE)
    def _chunk_meta(node):
        md = getattr(node, "metadata", {}) or {}
        try:
            cid = int(md.get("chunk_id")) if md.get("chunk_id") is not None else None
        except Exception:
            cid = None
        try:
            tot = int(md.get("total_chunks_page")) if md.get("total_chunks_page") is not None else None
        except Exception:
            tot = None
        return cid, tot

    calculations = getattr(result, "calculations", [])
    claim_evidence = build_claim_evidence(answer, source_nodes, checks, calculations)
    response = QueryResponse(
        answer=answer,
        sources_used=interp["sources"],
        rewritten_query=interp["rewritten_query"],
        sources=[
            SourceInfo(
                file=source_file(node),
                score=relevance_score(node),
                page=source_page(node),
                excerpt=_source_excerpt(node),
                chunk_id=_chunk_meta(node)[0],
                total_chunks_page=_chunk_meta(node)[1],
            )
            for node in source_nodes
        ],
        validation=ValidationInfo(
            verified=verified,
            total=len(checks),
            unverified=unverified,
            requires_review=bool(getattr(result, "clarification", None)) or bool(unverified) or any(item["status"] == "requires_review" for item in claim_evidence),
        ),
        citation_validation=CitationValidationInfo(
            verified=len(citation_checks) - len(unverified_citations),
            total=len(citation_checks),
            unverified=unverified_citations,
        ),
        numeric_citations=numeric_citations,
        rag_type=rag_type,
        rag_label=rag_label,
        timeseries_chart=timeseries_chart,
        calculations=calculations,
        claim_evidence=claim_evidence,
        ontology=ontology_report(question, source_nodes, calculations, getattr(result, "retrieval_paths", [])),
        clarification=getattr(result, "clarification", None),
        knowledge=getattr(result, "knowledge", {}),
    )
    diagnostics = QueryDiagnostics(
        sources=interp["sources"],
        chunks=len(source_nodes),
        verified=verified,
        total=len(checks),
        unverified=unverified,
        estimated_input_tokens=usage["estimated_input_tokens"],
        estimated_output_tokens=usage["estimated_output_tokens"],
        estimated_cost_usd=usage["estimated_cost_usd"],
    )
    return response, diagnostics
