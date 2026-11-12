import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from comparacao import common
from comparacao.footnotes import separate_table_footnotes
from comparacao.retrieval import BM25Index, diversify, initial_ranking, rrf_fuse, tokenize


def row(node_id, text, table="t1", strategy="row_per_chunk", source="a.xlsx"):
    return SimpleNamespace(text=f"{text}\nFonte: {source}", metadata={
        "node_id": node_id, "type": "table", "table_key": table, "chunk_strategy": strategy,
        "source_file": source})


def chunk(node_id, text, table=None):
    metadata = {"node_id": node_id, "type": "table" if table else "text"}
    if table:
        metadata["table_key"] = table
    return {"text": text, "source": "a", "page": 1, "number": 1, "metadata": metadata}


def test_footnote_rows_become_table_notes():
    nodes = [row("1", "Ano [coluna 1]: 2025\nPIB [coluna 2]: 1,59"),
             row("2", "Ano [coluna 1]: Nota: Os dados são preliminares e sujeitos a revisão."),
             row("3", "Ano [coluna 1]: Fonte: Fundação Seade."),
             row("4", "Ano [coluna 1]: Fonte: Fundação Seade."),
             row("5", "Ano [coluna 1]: Estado de São Paulo"),
             row("6", "Ano [coluna 1]: Fonte: IBGE.", table="t2")]
    kept, removed = separate_table_footnotes(nodes)
    assert removed == 4
    assert [node.metadata["node_id"] for node in kept] == ["1", "5"]
    assert json.loads(kept[0].metadata["table_footnotes"]) == [
        "Nota: Os dados são preliminares e sujeitos a revisão.", "Fonte: Fundação Seade."]


def test_full_tables_and_text_are_not_treated_as_footnotes():
    nodes = [row("1", "Ano [coluna 1]: Fonte: IBGE.", strategy="full_table"),
             SimpleNamespace(text="Fonte: IBGE.", metadata={"node_id": "2", "type": "text"})]
    kept, removed = separate_table_footnotes(nodes)
    assert removed == 0 and len(kept) == 2


def test_context_shows_table_notes():
    item = {"text": "PIB: 1,59", "source": "a.xlsx", "page": "Tabela 3",
            "metadata": {"table_footnotes": json.dumps(["Nota: dados preliminares."])}}
    context, used = common.pack_results([item], budget=1000)
    assert "Notas da tabela: Nota: dados preliminares." in context and used == [item]


def test_tokenizer_keeps_codes_and_numbers_and_drops_accents():
    assert tokenize("Classe CNAE 47.32-6 de São Paulo: R$ 3.277,8") == [
        "classe", "cnae", "47.32-6", "sao", "paulo", "r", "3.277,8"]


def test_bm25_finds_exact_code():
    chunks = [chunk("a", "47.32-6 Comércio varejista de lubrificantes"),
              chunk("b", "86.40-2 Atividades de serviços de complementação diagnóstica"),
              chunk("c", "Comércio varejista de combustíveis")]
    assert [item["metadata"]["node_id"] for item in BM25Index(chunks).search("classe CNAE 47.32-6", 2)][0] == "a"


def test_rrf_rewards_agreement_and_records_ranks():
    fused = rrf_fuse({"vetorial": [chunk("a", ""), chunk("b", "")], "bm25": [chunk("b", ""), chunk("c", "")]})
    assert [item["metadata"]["node_id"] for item in fused] == ["b", "a", "c"]
    assert fused[0]["ranks"] == {"vetorial": 2, "bm25": 1}


def test_diversify_limits_rows_per_table_keeping_order():
    ranking = [chunk("1", "", "t"), chunk("2", "", "t"), chunk("3", "", "t"), chunk("4", ""), chunk("5", "", "u")]
    assert [item["metadata"]["node_id"] for item in diversify(ranking, 4, 2)] == ["1", "2", "4", "5"]
    assert [item["metadata"]["node_id"] for item in diversify(ranking, 4, 0)] == ["1", "2", "3", "4"]


def test_dense_mode_keeps_pure_vector_ranking():
    dense = [chunk("1", "", "t"), chunk("2", "", "t"), chunk("3", "")]
    rag = SimpleNamespace(search=lambda question, limit, payload: dense[:limit])
    settings = {"retrieval_mode": "dense", "candidate_pool": 3, "top_k": 2, "rrf_k": 60, "max_per_table": 0}
    result = initial_ranking("pergunta", rag, None, settings)
    assert [item["metadata"]["node_id"] for item in result] == ["1", "2"]
    assert result[0]["ranks"] == {"vetorial": 1}


def test_old_profiles_default_to_dense_without_diversification(tmp_path):
    from comparacao.profile import load_profile
    settings = json.loads(common.CONFIG_PATH.read_text(encoding="utf-8"))
    for key in ("retrieval_mode", "candidate_pool", "rrf_k", "max_per_table", "embedding_provider",
                "reranker", "rerank_pool", "min_text_chars", "small_table_rows", "small_table_chars"):
        settings.pop(key, None)
    path = tmp_path / "perfil.json"
    path.write_text(json.dumps(settings), encoding="utf-8")
    loaded = load_profile(path)
    assert (loaded["retrieval_mode"], loaded["candidate_pool"], loaded["max_per_table"]) == ("dense", loaded["top_k"], 0)
    assert (loaded["reranker"], loaded["min_text_chars"], loaded["small_table_rows"]) == ("", 0, 0)


def text_node(node_id, text, source="a.pdf"):
    return SimpleNamespace(text=text, metadata={"node_id": node_id, "type": "text", "source_file": source})


def test_short_fragments_are_appended_to_previous_chunk_and_kept():
    from comparacao.chunk_repair import join_short_fragments
    nodes = [text_node("1", "Encadeamento permite comparar períodos." * 10),
             text_node("2", "Porém tem a desvantagem da perda da aditividade"),
             text_node("3", "fragmento seguinte"),
             text_node("4", "início de outra fonte", source="b.pdf")]
    kept, joined = join_short_fragments(nodes, 250)
    assert joined == 2 and len(kept) == 4
    assert kept[0].text.endswith("perda da aditividade\nfragmento seguinte")
    assert kept[3].text == "início de outra fonte"


def test_small_split_tables_are_merged_and_large_ones_kept():
    from comparacao.chunk_repair import merge_small_tables
    small = [row(f"s{i}", f"variavel [coluna 1]: cod_{i}", table="dic") for i in range(3)]
    for node in small:
        node.metadata["table_structure"] = "{}"
    large = [row(f"l{i}", f"Ano [coluna 1]: {2000 + i}", table="serie") for i in range(5)]
    kept, merged = merge_small_tables(small + large, max_rows=4, max_chars=6000)
    assert merged == 1
    assert [node.metadata["node_id"] for node in kept] == ["s0", "l0", "l1", "l2", "l3", "l4"]
    assert kept[0].metadata["chunk_strategy"] == "full_table" and kept[0].metadata["merged_rows"] == 3
    assert "table_structure" not in kept[0].metadata
    assert "cod_0" in kept[0].text and "cod_2" in kept[0].text


def test_reranker_reorders_only_the_head_before_diversification():
    dense = [chunk(str(i), f"t{i}") for i in range(1, 5)]
    rag = SimpleNamespace(search=lambda question, limit, payload: dense[:limit])
    reranker = SimpleNamespace(rerank=lambda question, items: [
        {**item, "ranks": {**item["ranks"], "rerank": position}}
        for position, item in enumerate(reversed(items), 1)])
    settings = {"retrieval_mode": "dense", "candidate_pool": 4, "top_k": 3, "rrf_k": 60,
                "max_per_table": 0, "rerank_pool": 2}
    result = initial_ranking("pergunta", rag, None, settings, reranker=reranker)
    assert [item["metadata"]["node_id"] for item in result] == ["2", "1", "3"]
    assert result[0]["ranks"] == {"vetorial": 2, "rerank": 1}


def test_ontology_filter_drops_explicit_conflicts_and_keeps_incomplete_data(monkeypatch):
    from comparacao import common
    from comparacao.retrieval import ontology_filter
    common.apply_profile(strict=True)
    common.graph_modules()
    ranking = [{"text": "PIB de São Paulo em 2023 cresceu 3,2%.", "metadata": {"node_id": "ok"}},
               {"text": "PIB do Rio de Janeiro em 2019 cresceu 1,1%.", "metadata": {"node_id": "conflict"}},
               {"text": "Texto sem recorte identificável.", "metadata": {"node_id": "incomplete"}}]
    kept = [item["metadata"]["node_id"] for item in ontology_filter("PIB de São Paulo em 2023", ranking)]
    assert "ok" in kept and "incomplete" in kept and "conflict" not in kept


def test_extra_reserve_keeps_the_top_k_prefix():
    settings = {"candidate_pool": 5, "top_k": 2, "retrieval_mode": "dense", "rrf_k": 60,
                "max_per_table": 0, "rerank_pool": 5}
    items = [{"text": str(i), "metadata": {"node_id": str(i)}, "score": 1 - i / 10} for i in range(5)]
    rag = SimpleNamespace(search=lambda question, pool, payload: items[:pool])
    base = [item["metadata"]["node_id"] for item in initial_ranking("q", rag, None, settings)]
    wide = [item["metadata"]["node_id"] for item in initial_ranking("q", rag, None, settings, extra=2)]
    assert base == ["0", "1"] and wide[:2] == base and wide == ["0", "1", "2", "3"]


def test_exact_structured_rows_go_first_capped_and_lexical_rows_are_ignored():
    from comparacao.retrieval import EXACT_CAP
    items = [{"text": str(i), "metadata": {"node_id": str(i)}, "score": 1 - i / 10} for i in range(4)]
    rag = SimpleNamespace(search=lambda question, pool, payload: items[:pool])
    exact = [{"text": f"e{i}", "metadata": {"node_id": f"e{i}", "retrieval_method": "structured_exact"}, "score": 1.0}
             for i in range(EXACT_CAP + 1)]
    lexical = [{"text": "l", "metadata": {"node_id": "l", "retrieval_method": "structured_lexical"}, "score": .75}]
    settings = {"candidate_pool": 4, "top_k": 4, "retrieval_mode": "dense", "rrf_k": 60, "max_per_table": 0,
                "rerank_pool": 4}
    result = initial_ranking("q", rag, None, settings, structured=lambda question: exact + lexical)
    ids = [item["metadata"]["node_id"] for item in result]
    assert ids[:EXACT_CAP] == [f"e{i}" for i in range(EXACT_CAP)]  # exatas à frente, no máximo EXACT_CAP
    assert "e2" not in ids[:EXACT_CAP] and len(ids) == 4
    assert "l" not in ids  # a linha só lexical é descartada
    assert result[0]["ranks"] == {"estruturada_exata": 1}
    # Sem busca estruturada, nada muda.
    plain = initial_ranking("q", rag, None, settings)
    assert [item["metadata"]["node_id"] for item in plain] == ["0", "1", "2", "3"]


def test_context_shows_table_title_and_all_notes_for_table_rows():
    from comparacao.common import pack_results
    row = {"text": "Período: 2023\nValor: 3,2", "source": "t.xlsx", "page": "Tabela 1",
           "metadata": {"type": "table", "table_title": "Tabela 1 | Taxa de crescimento, com ajuste sazonal",
                        "table_footnotes": json.dumps(["Nota: dados preliminares."]),
                        "table_notes": json.dumps(["(1) Base: ano anterior."])}}
    text, used = pack_results([row], budget=10000)
    assert "Título da tabela: Tabela 1 | Taxa de crescimento, com ajuste sazonal" in text
    assert "Notas da tabela: Nota: dados preliminares." in text
    assert "Notas do documento: (1) Base: ano anterior." in text
    # Trechos sem esses metadados (texto de PDF) e metadados malformados continuam funcionando.
    plain = {"text": "Texto.", "source": "a.pdf", "page": 1, "metadata": {"type": "text", "table_notes": "{inválido"}}
    text, _ = pack_results([plain], budget=10000)
    assert "Título" not in text and "Notas" not in text
