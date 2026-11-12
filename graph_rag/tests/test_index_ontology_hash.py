"""Mudança só na ontologia reanota nós e metadados, sem recalcular embeddings."""
import json

import chromadb
from llama_index.core import Document
from llama_index.core.schema import MetadataMode, TextNode

import domain_ontology
import index_sync as sync
from index_manifest import _pipeline_fingerprint, data_snapshot, ontology_fingerprint, save_manifest, stored_pipeline
from indexing import load_nodes_cache, reannotate_index, save_nodes_cache


class Log:
    def info(self, *_args):
        pass

    def warning(self, *_args):
        pass


class FakeClient:
    def get_or_create_collection(self, _name):
        return type("Collection", (), {"count": lambda self: 1})()


def prepared(tmp_path, monkeypatch, ontology_hash):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "boletim.txt").write_text("conteúdo", encoding="utf-8")
    db_path = tmp_path / "db"
    snapshot = data_snapshot(str(data_dir))
    save_manifest(str(db_path), {**snapshot, "__embed_dim": 768}, ontology_hash=ontology_hash)
    save_nodes_cache([TextNode(id_="a", text="conteúdo", metadata={"source_file": "boletim.txt"})], str(db_path))
    monkeypatch.setattr(sync.chromadb, "PersistentClient", lambda path: FakeClient())
    return data_dir, db_path


def test_pipeline_nao_depende_da_ontologia(tmp_path, monkeypatch):
    before, ontology_before = _pipeline_fingerprint(), ontology_fingerprint()
    path = tmp_path / "ext.json"
    path.write_text(json.dumps({"schema_version": domain_ontology.SCHEMA_VERSION, "indicators": [
        {"id": "arrecadacao", "label": "Arrecadação", "pattern": "arrecadacao", "reviewed": True}]}), encoding="utf-8")
    monkeypatch.setenv("RAG_ONTOLOGY_EXTENSIONS", str(path))
    try:
        assert ontology_fingerprint() != ontology_before
        assert _pipeline_fingerprint() == before
    finally:
        monkeypatch.undo()
        domain_ontology._sync_vocabulary()


def test_so_ontologia_mudou_reanota_sem_reler_nem_reembutir(tmp_path, monkeypatch):
    data_dir, db_path = prepared(tmp_path, monkeypatch, ontology_hash="antigo")
    calls = {}
    monkeypatch.setattr(sync, "reannotate_index", lambda db, name: calls.setdefault("reannotated", (db, name)) and True)
    monkeypatch.setattr(sync, "create_or_load_index", lambda nodes, **_: calls.setdefault("index", nodes) or "indice")
    monkeypatch.setattr(sync, "load_documents", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("não deve reler")))
    index, changed = sync.sync_standard_index(str(data_dir), str(db_path), Log())
    assert index == "indice" and calls["index"] == []
    assert calls["reannotated"] == (str(db_path), "estatisticas")
    assert changed == ["__ontology"]
    pipeline = stored_pipeline(str(db_path))
    assert pipeline["ontology_hash"] == ontology_fingerprint() and pipeline["embed_dim"] == 768


def test_ontologia_igual_nao_reanota(tmp_path, monkeypatch):
    data_dir, db_path = prepared(tmp_path, monkeypatch, ontology_hash=None)
    monkeypatch.setattr(sync, "reannotate_index", lambda *_: (_ for _ in ()).throw(AssertionError("não deve reanotar")))
    monkeypatch.setattr(sync, "create_or_load_index", lambda nodes, **_: "indice")
    assert sync.sync_standard_index(str(data_dir), str(db_path), Log()) == ("indice", [])


def test_falha_na_reanotacao_reconstroi_indice(tmp_path, monkeypatch):
    data_dir, db_path = prepared(tmp_path, monkeypatch, ontology_hash="antigo")
    calls = {}
    monkeypatch.setattr(sync, "reannotate_index", lambda *_: (_ for _ in ()).throw(RuntimeError("coleção")))
    monkeypatch.setattr(sync, "load_documents", lambda *_a, **_k: [Document(text="conteúdo", metadata={"source_file": "boletim.txt"})])
    monkeypatch.setattr(sync, "process_documents", lambda docs: [TextNode(text="conteúdo", metadata={"source_file": "boletim.txt"})])
    monkeypatch.setattr(sync, "create_or_load_index", lambda nodes, **_: calls.setdefault("index", nodes) and "indice")
    monkeypatch.setattr(sync, "_record_embed_dim", lambda snapshot: None)
    index, changed = sync.sync_standard_index(str(data_dir), str(db_path), Log())
    assert index == "indice" and len(calls["index"]) == 1
    assert "__ontology" in changed


def test_reanotacao_atualiza_cache_e_metadados_e_preserva_vetor(tmp_path):
    from llama_index.core.vector_stores.utils import node_to_metadata_dict
    db_path = str(tmp_path / "db")
    node = TextNode(id_="a", text="Comércio internacional em 2023.", metadata={"source_file": "fonte.pdf"})
    domain_ontology.annotate_node(node)
    # Anotação gravada por uma versão anterior da ontologia.
    node.metadata["ontology_region"] = "brasil"
    node.excluded_embed_metadata_keys.append("ontology_region")
    node.excluded_llm_metadata_keys.append("ontology_region")
    embed_text = node.get_content(metadata_mode=MetadataMode.EMBED)
    save_nodes_cache([node], db_path)
    collection = chromadb.PersistentClient(path=db_path).get_or_create_collection("estatisticas")
    collection.add(ids=["a"], embeddings=[[0.25, 0.75]], metadatas=[node_to_metadata_dict(node, remove_text=True, flat_metadata=True)])

    assert reannotate_index(db_path, "estatisticas") is True

    cached = load_nodes_cache(db_path)[0]
    assert "ontology_region" not in cached.metadata and cached.metadata["ontology_period"] == "2023"
    assert cached.get_content(metadata_mode=MetadataMode.EMBED) == embed_text
    stored = collection.get(ids=["a"], include=["metadatas", "embeddings"])
    assert "ontology_region" not in stored["metadatas"][0]
    assert "ontology_region" not in json.loads(stored["metadatas"][0]["_node_content"])["metadata"]
    assert list(stored["embeddings"][0]) == [0.25, 0.75]


def test_reanotacao_sem_cache_pede_reconstrucao(tmp_path):
    assert reannotate_index(str(tmp_path / "vazio"), "estatisticas") is False
