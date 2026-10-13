from unittest.mock import Mock

import pytest

from indexing import _insert_nodes_in_batches


def test_batches_preserve_order_and_tail(monkeypatch):
    monkeypatch.setenv("RAG_CHROMA_WRITE_BATCH_SIZE", "16")
    index = Mock()
    nodes = list(range(35))
    _insert_nodes_in_batches(index, nodes)
    assert [call.args[0] for call in index.insert_nodes.call_args_list] == [
        nodes[:16], nodes[16:32], nodes[32:]
    ]


def test_failure_stops_later_batches(monkeypatch):
    monkeypatch.setenv("RAG_CHROMA_WRITE_BATCH_SIZE", "16")
    index = Mock()
    index.insert_nodes.side_effect = [None, RuntimeError("embedding failed")]
    with pytest.raises(RuntimeError, match="embedding failed"):
        _insert_nodes_in_batches(index, list(range(50)))
    assert index.insert_nodes.call_count == 2


def test_empty_nodes_do_not_insert():
    index = Mock()
    _insert_nodes_in_batches(index, [])
    index.insert_nodes.assert_not_called()
