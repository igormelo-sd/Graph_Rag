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


def test_chunk_table_handles_various_table_notes_formats():
    from processing import _chunk_table
    text = "| Indicador | 2022 |\n|---|---|\n| PIB | 100 |"

    # Caso 1: table_notes como lista Python
    doc1 = Document(text=text, metadata={"type": "table", "source_file": "f1.csv", "page": 1, "table_notes": ["Nota em lista"]})
    nodes1 = _chunk_table(doc1)
    assert len(nodes1) == 1

    # Caso 2: table_notes como string não-JSON
    doc2 = Document(text=text, metadata={"type": "table", "source_file": "f2.csv", "page": 1, "table_notes": "Nota de rodapé textual"})
    nodes2 = _chunk_table(doc2)
    assert len(nodes2) == 1

    # Caso 3: table_notes como JSON válido
    doc3 = Document(text=text, metadata={"type": "table", "source_file": "f3.csv", "page": 1, "table_notes": '["Nota JSON"]'})
    nodes3 = _chunk_table(doc3)
    assert len(nodes3) == 1


def test_sanitize_nodes_does_not_mutate_cached_node():
    from llama_index.core.schema import TextNode, NodeWithScore
    from provenance import sanitize_nodes, sanitize_text

    raw_text = "Texto com caractere nulo \x00 e controle \x1b final"
    original_node = TextNode(text=raw_text)
    node_with_score = NodeWithScore(node=original_node, score=0.85)

    sanitized = sanitize_nodes([node_with_score])
    assert len(sanitized) == 1
    # Nó retornado foi limpo
    assert "\x00" not in sanitized[0].node.text
    assert "\x1b" not in sanitized[0].node.text
    assert sanitized[0].score == 0.85
    # Nó original no cache NÃO foi mutado
    assert original_node.text == raw_text
    assert original_node is not sanitized[0].node


def test_assign_page_metadata_handles_none_and_file_name_symmetrically():
    from types import SimpleNamespace
    from provenance import assign_page_metadata

    # Documento e nó com source_file ausente (None)
    doc_none = SimpleNamespace(metadata={"section": "Introdução"})
    node_none = SimpleNamespace(metadata={})
    assign_page_metadata([node_none], [doc_none])
    assert node_none.metadata["chunk_id"] == 1
    assert node_none.metadata["total_chunks_page"] == 1
    assert node_none.metadata["section"] == "Introdução"

    # Documento e nó identificados por file_name em vez de source_file
    doc_fname = SimpleNamespace(metadata={"file_name": "relatorio.pdf", "page": 3, "section": "Setores"})
    node_fname = SimpleNamespace(metadata={"file_name": "relatorio.pdf", "page": 3})
    assign_page_metadata([node_fname], [doc_fname])
    assert node_fname.metadata["section"] == "Setores"
