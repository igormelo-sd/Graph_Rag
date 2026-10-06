"""Contratos HTTP compartilhados pelas engines RAG."""
from __future__ import annotations

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4_000)


class SourceInfo(BaseModel):
    file: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    page: str | int | None = None
    excerpt: str = Field(default="", max_length=4_000)
    chunk_id: int | None = Field(default=None, ge=1)
    total_chunks_page: int | None = Field(default=None, ge=1)


class ValidationInfo(BaseModel):
    verified: int = Field(ge=0)
    total: int = Field(ge=0)
    unverified: list[str]
    method: str = "contextual_heuristic"
    requires_review: bool = False


class CitationValidationInfo(BaseModel):
    verified: int = Field(ge=0)
    total: int = Field(ge=0)
    unverified: list[str]


class NumericCitationInfo(BaseModel):
    value: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    source_index: int = Field(ge=0)
    file: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    page: str | int | None = None
    snippet: str = Field(default="", max_length=1_000)
    content_type: str = Field(default="text", min_length=1, max_length=32)
    claim: str = Field(default="", max_length=1_000)
    explanation: str = Field(default="", max_length=400)


class QueryResponse(BaseModel):
    answer: str = Field(min_length=1)
    sources_used: list[str]
    rewritten_query: str
    sources: list[SourceInfo]
    validation: ValidationInfo
    citation_validation: CitationValidationInfo
    numeric_citations: list[NumericCitationInfo] = Field(default_factory=list)
    rag_type: str
    rag_label: str
    timeseries_chart: dict | None = Field(default=None)
    claim_evidence: list[dict] = Field(default_factory=list)
    calculations: list[dict] = Field(default_factory=list)
    usage: dict = Field(default_factory=dict)
    ontology: dict = Field(default_factory=dict)
    clarification: dict | None = None
    knowledge: dict = Field(default_factory=dict)
