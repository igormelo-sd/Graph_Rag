import json
import pytest
from llama_index.core.schema import TextNode, NodeRelationship, RelatedNodeInfo
from indexing import save_nodes_cache, load_nodes_cache


def test_jsonl_preserves_identity_metadata_and_relationships(tmp_path):
    node = TextNode(id_="child", text="São Paulo", metadata={"source_file": "a.pdf", "nested": {"year": 2024}},
                    relationships={NodeRelationship.PARENT: RelatedNodeInfo(node_id="parent")})
    save_nodes_cache([node], str(tmp_path))
    restored, = load_nodes_cache(str(tmp_path))
    assert restored.node_id == node.node_id
    assert restored.text == node.text
    assert restored.metadata == node.metadata
    assert restored.relationships == node.relationships


@pytest.mark.parametrize("content", ["", "not json", '{"schema_version": 99}\n', '{"schema_version": 1}\n{}\n'])
def test_invalid_cache_warns_without_partial_results(tmp_path, caplog, content):
    (tmp_path / "bm25_nodes.jsonl").write_text(content, encoding="utf-8")
    assert load_nodes_cache(str(tmp_path)) == []
    assert "reconstrua" in caplog.text


def test_legacy_pickle_is_never_deserialized(tmp_path, caplog):
    (tmp_path / "bm25_nodes.pkl").write_bytes(b"legacy pickle")
    assert load_nodes_cache(str(tmp_path)) == []
    assert "legado" in caplog.text
