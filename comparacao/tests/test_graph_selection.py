import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from comparacao import graph_selection
from comparacao.graph_selection import accept_extras


def item(node_id, table=None, origin="entity"):
    metadata = {"type": "table", "table_key": table} if table else {"type": "text"}
    metadata["graph_origin"] = origin
    return SimpleNamespace(node_id=node_id, node=SimpleNamespace(text=node_id), metadata=metadata, score=None)


class FixedReranker:
    def __init__(self, scores):
        self.scores = scores

    def score(self, question, texts):
        return [self.scores[text] for text in texts]


def test_extras_need_fraction_of_weakest_initial_and_respect_table_limit():
    initial = [item("i1", "t"), item("i2", "t")]
    candidates = [item("weak"), item("same_table", "t"), item("good", origin="label"), item("tie", origin="query")]
    reranker = FixedReranker({"i1": 0.9, "i2": 0.4, "weak": 0.05, "same_table": 0.95, "good": 0.5, "tie": 0.1})
    accepted, diagnostics = accept_extras("pergunta", initial, candidates, reranker, max_per_table=2)
    assert [extra.node_id for extra in accepted] == ["good", "tie"]
    assert diagnostics["threshold"] == graph_selection.SCORE_RATIO * 0.4 == 0.1
    assert diagnostics["candidates"] == {"entity": 2, "label": 1, "query": 1}
    assert [entry["origin"] for entry in diagnostics["accepted"]] == ["label", "query"]


def test_extras_are_capped(monkeypatch):
    monkeypatch.setattr(graph_selection, "EXTRA_LIMIT", 1)
    candidates = [item("a"), item("b")]
    accepted, _ = accept_extras("pergunta", [item("i")], candidates, FixedReranker({"i": 0.1, "a": 0.9, "b": 0.8}), 2)
    assert [extra.node_id for extra in accepted] == ["a"]


def test_without_reranker_graph_order_is_kept():
    accepted, diagnostics = accept_extras("pergunta", [item("i")], [item("b"), item("a")], None, 2)
    assert [extra.node_id for extra in accepted] == ["b", "a"]
    assert diagnostics["threshold"] is None


def test_linked_dictionary_and_notes_skip_the_threshold_up_to_the_cap():
    import json
    from comparacao.graph_selection import LINKED_CAP, is_linked

    def make(identity, origin, relation=None):
        metadata = {"type": "text", "graph_origin": origin}
        if relation:
            metadata["graph_paths"] = json.dumps([{"relation": relation}])
        return SimpleNamespace(node_id=identity, node=SimpleNamespace(text=identity), metadata=metadata, score=None)

    dictionary = make("d", "documentary", "DICIONARIO_DE")
    note, third = make("n", "documentary", "TEM_NOTA"), make("n2", "documentary", "TEM_NOTA")
    strong, other = make("s", "label"), make("o", "documentary", "TEM_TITULO")
    assert is_linked(dictionary) and not is_linked(strong) and not is_linked(other)
    reranker = FixedReranker({"i": 1.0, "d": 0.0, "n": 0.0, "n2": 0.0, "s": 0.9, "o": 0.0})  # vinculados abaixo do limiar
    accepted, diagnostics = accept_extras("pergunta", [item("i")], [strong, dictionary, note, third, other], reranker, 2)
    ids = [candidate.node_id for candidate in accepted]
    assert ids[:LINKED_CAP] == ["d", "n"] and "n2" not in ids and "o" not in ids and "s" in ids
    assert [entry["linked"] for entry in diagnostics["accepted"]][:LINKED_CAP] == [True, True]
