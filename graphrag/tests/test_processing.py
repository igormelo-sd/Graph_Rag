from llama_index.core import Document
from llama_index.core.llms import MockLLM

from processing import (
    _enrich_table_metadata,
    _get_text_pipeline,
    llm_ingest_enrichment_enabled,
)


def test_text_extractors_use_the_configured_llm():
    configured_llm = MockLLM(max_tokens=8)

    pipeline = _get_text_pipeline(configured_llm, enrich_metadata=True)

    title_extractor = pipeline.transformations[1]
    keyword_extractor = pipeline.transformations[2]
    assert title_extractor.llm is configured_llm
    assert keyword_extractor.llm is configured_llm
    assert title_extractor.raise_on_error is False
    assert keyword_extractor.raise_on_error is False


def test_ollama_skips_llm_metadata_by_default(monkeypatch):
    monkeypatch.setenv("RAG_LLM_PROVIDER", "ollama")
    monkeypatch.delenv("RAG_INGEST_LLM_ENRICHMENT", raising=False)

    assert llm_ingest_enrichment_enabled() is False
    pipeline = _get_text_pipeline()
    assert len(pipeline.transformations) == 1


def test_ollama_llm_metadata_can_be_enabled(monkeypatch):
    monkeypatch.setenv("RAG_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("RAG_INGEST_LLM_ENRICHMENT", "1")

    assert llm_ingest_enrichment_enabled() is True


def test_table_metadata_has_deterministic_temporal_fallback():
    document = Document(
        text="""| Ano | Empregos |\n| --- | --- |\n| 2022 | 10 |\n| 2023 | 12 |""",
        metadata={"source_file": "emprego.csv", "type": "table"},
    )

    metadata = _enrich_table_metadata(document, llm=None)

    assert metadata["table_periodo"] == "2022-2023"
    assert metadata["table_granularidade"] == "anual"
    assert metadata["table_indicadores"] == "Ano, Empregos"


def test_cabecalho_generico_de_camelot_preserva_linha_literal():
    from processing import _markdown_to_df
    frame = _markdown_to_df("| 0 | 1 | 2 |\n|---|---|---|\n| Indicador | 2022 | 2023 |\n| PIB | 100 | 120 |")
    assert list(frame.columns) == ["Indicador", "2022", "2023"]
    assert frame.iloc[0].tolist() == ["PIB", "100", "120"]


def test_cabecalho_duplicado_nao_descarta_celulas_silenciosamente():
    from processing import _chunk_table
    text = "| Indicador | Valor | Valor |\n|---|---|---|\n| PIB | 100 | 120 |"
    document = Document(text=text, metadata={"type": "table", "source_file": "fonte.pdf", "page": 1})
    nodes = _chunk_table(document)
    assert len(nodes) == 1 and nodes[0].text == text
