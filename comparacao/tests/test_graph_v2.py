import sys
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from comparacao import common
from comparacao.graph_v2 import accept_extras, document_context, entity_candidates

common.graph_modules()


def graph(chunks, edges):
    outgoing, incoming = defaultdict(list), defaultdict(list)
    for label, source, target in edges:
        edge = SimpleNamespace(label=label, source_id=source, target_id=target, properties={})
        outgoing[source].append(edge)
        incoming[target].append(edge)
    return SimpleNamespace(_chunk_ids=set(chunks), _outgoing=outgoing, _incoming=incoming)


def test_rare_shared_entity_outranks_hub_regardless_of_node_id():
    chunks = ["seed"] + [f"hub{i}" for i in range(30)] + ["zz_rare"]
    edges = [("HAS_ENTITY", "seed", "Estado:SP"), ("HAS_ENTITY", "seed", "Indicador:CNAE")]
    edges += [("HAS_ENTITY", f"hub{i}", "Estado:SP") for i in range(30)]
    edges += [("HAS_ENTITY", "zz_rare", "Indicador:CNAE")]
    ranked = entity_candidates(graph(chunks, edges), ["seed"], limit=3)
    assert ranked[0][0] == "zz_rare"
    assert "seed" not in [chunk for chunk, _, _ in ranked]


def test_table_brings_notes_and_title_but_not_sibling_rows():
    chunks = ["row1", "row2", "row3", "note", "title"]
    edges = [("REPRESENTADA_EM", "Tabela:t", row) for row in ("row1", "row2", "row3")]
    edges += [("TEM_NOTA", "Tabela:t", "note"), ("TEM_TITULO", "Tabela:t", "title")]
    found = [key for key, _ in document_context(graph(chunks, edges), ["row1"], limit=6)]
    assert found == ["note", "title"]


def item(node_id, table=None):
    metadata = {"type": "table", "table_key": table} if table else {"type": "text"}
    return SimpleNamespace(node_id=node_id, node=SimpleNamespace(text=node_id), metadata=metadata, score=None)


class FixedReranker:
    def __init__(self, scores):
        self.scores = scores

    def score(self, question, texts):
        return [self.scores[text] for text in texts]


def test_extras_need_score_relative_to_initial_and_respect_table_limit():
    initial = [item("i1", "t"), item("i2", "t")]
    candidates = [item("weak"), item("same_table", "t"), item("good")]
    reranker = FixedReranker({"i1": 0.9, "i2": 0.4, "weak": 0.1, "same_table": 0.95, "good": 0.3})
    accepted, diagnostics = accept_extras("pergunta", initial, candidates, reranker, max_per_table=2)
    assert [extra.node_id for extra in accepted] == ["good"]
    assert diagnostics["threshold"] == 0.2
