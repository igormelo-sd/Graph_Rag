import sys
from pathlib import Path
from types import SimpleNamespace

from llama_index.core.schema import NodeWithScore, TextNode

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from comparacao import common


def activate():
    common.apply_profile(strict=True)
    common.graph_modules()
    from comparacao.lexical import LexicalExpander, terms
    return LexicalExpander, terms


def row(identity, text, table="t1", source="pib.csv"):
    return TextNode(id_=identity, text=text, metadata={"type": "table", "source_file": source, "table_key": table,
                                                       "page": "Planilha", "chunk_id": 1})


def test_terms_keep_numbers_and_drop_stopwords_and_accents():
    _, terms = activate()
    assert terms("Qual o PIB de São José em 2020?") >= {"pib", "sao", "jose", "2020"}
    assert not terms("qual foi o valor entre as") & {"qual", "valor", "entre"}


def test_candidates_come_from_the_seed_table_and_document_by_rare_terms():
    Expander, _ = activate()
    nodes = [row("campinas", "Município: Campinas\nPIB: 100"), row("santos", "Município: Santos\nPIB: 90"),
             row("sorocaba", "Município: Sorocaba\nPIB: 80"),
             row("outra", "Município: Santos\nPIB: 1", table="t2", source="outra.csv")]
    expander = Expander(nodes)
    found = expander.candidates([NodeWithScore(node=nodes[0], score=1.0)], "PIB de Santos", limit=3)
    ids = [item.node_id for item in found]
    assert ids[0] == "santos"                      # termo raro da pergunta, na mesma tabela
    assert "outra" not in ids and "campinas" not in ids  # outra tabela/documento e a própria semente ficam de fora
    assert expander.candidates([NodeWithScore(node=nodes[0], score=1.0)], "de por com", limit=3) == []
    # As cópias devolvidas não alteram os nós do índice.
    found[0].node.metadata["graph_origin"] = "label"
    assert "graph_origin" not in nodes[1].metadata
