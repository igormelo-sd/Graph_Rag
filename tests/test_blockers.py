from pathlib import Path

import pandas as pd
from llama_index.core import Document
from llama_index.core.schema import TextNode

from index_manifest import (
    data_snapshot,
    detect_changes,
    load_manifest,
    resolve_data_dir,
    resolve_db_dir,
    save_manifest,
)
from indexing import (
    load_nodes_cache,
    merge_nodes_cache,
    reset_nodes_cache,
    save_nodes_cache,
)
from ingestion import load_documents
from provenance import relevance_score, source_file, source_page
from tables_retriever import _is_static_table
from timeseries_retriever import _df_is_valid_timeseries, _is_temporal_table
from runtime import estimate_tokens, limit_context


class _Node:
    def __init__(self, metadata, score=None):
        self.metadata = metadata
        self.score = score


def test_manifest_detecta_subdiretorios_e_remocao(tmp_path):
    data_dir = tmp_path / "data"
    nested = data_dir / "setor"
    nested.mkdir(parents=True)
    document = nested / "boletim.txt"
    document.write_text("conteúdo", encoding="utf-8")

    first = data_snapshot(str(data_dir))
    assert first["__pipeline"]
    assert [k for k in first if k != "__pipeline"] == ["setor/boletim.txt"]

    document.unlink()
    second = data_snapshot(str(data_dir))
    assert detect_changes(second, first) == ["setor/boletim.txt"]


def test_diretorio_de_dados_local_compartilhado_e_resolvido(tmp_path):
    engine_dir = tmp_path / "rag_principal"
    (engine_dir / "data").mkdir(parents=True)
    shared_dir = tmp_path / "data"
    shared_dir.mkdir()
    (shared_dir / "boletim.pdf").write_bytes(b"pdf")

    assert resolve_data_dir(str(engine_dir)) == str(shared_dir.resolve())


def test_diretorio_da_engine_tem_precedencia_quando_contem_documentos(tmp_path):
    engine_dir = tmp_path / "rag_principal"
    engine_data = engine_dir / "data"
    engine_data.mkdir(parents=True)
    (engine_data / "container.pdf").write_bytes(b"pdf")
    shared_dir = tmp_path / "data"
    shared_dir.mkdir()
    (shared_dir / "local.pdf").write_bytes(b"pdf")

    assert resolve_data_dir(str(engine_dir)) == str(engine_data.resolve())


def test_diretorio_do_banco_pode_ser_isolado_por_ambiente(tmp_path, monkeypatch):
    engine_dir = tmp_path / "rag_principal"
    isolated_db = tmp_path / "chroma_db_boletins_economia"
    monkeypatch.setenv("RAG_DB_DIR", str(isolated_db))

    assert resolve_db_dir(str(engine_dir)) == str(isolated_db.resolve())


def test_diretorio_do_banco_mantem_padrao_sem_configuracao(tmp_path, monkeypatch):
    engine_dir = tmp_path / "rag_principal"
    monkeypatch.delenv("RAG_DB_DIR", raising=False)

    assert resolve_db_dir(str(engine_dir)) == str((engine_dir / "chroma_db").resolve())


def test_manifest_corrompido_forca_reconstrucao(tmp_path):
    db = tmp_path / "db"
    db.mkdir()
    (db / "indexed_manifest.json").write_text("{", encoding="utf-8")
    assert load_manifest(str(db)) == {}

    snapshot = {"a.txt": {"mtime_ns": 1, "size": 2}}
    save_manifest(str(db), snapshot)
    loaded = load_manifest(str(db))
    assert loaded["a.txt"] == {"mtime_ns": 1, "size": 2}
    assert loaded["__pipeline"]


def test_reset_cache_remove_nos_bm25_obsoletos(tmp_path):
    save_nodes_cache(["obsoleto"], str(tmp_path))
    assert load_nodes_cache(str(tmp_path)) == ["obsoleto"]
    reset_nodes_cache(str(tmp_path))
    assert load_nodes_cache(str(tmp_path)) == []


def test_ingestao_preserva_caminho_relativo_da_fonte(tmp_path):
    data_dir = tmp_path / "data"
    nested = data_dir / "regional"
    nested.mkdir(parents=True)
    (nested / "boletim.txt").write_text("Informação econômica relevante.", encoding="utf-8")
    docs = load_documents(str(data_dir))
    assert docs[0].metadata["source_file"] == "regional/boletim.txt"


def test_ingestao_seletiva_processa_somente_fontes_pedidas(tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "antigos").mkdir(parents=True)
    (data_dir / "novos").mkdir()
    (data_dir / "antigos" / "a.txt").write_text("antigo", encoding="utf-8")
    (data_dir / "novos" / "b.txt").write_text("novo", encoding="utf-8")

    docs = load_documents(
        str(data_dir),
        source_files=["novos/b.txt"],
        save_output=False,
    )

    assert [doc.metadata["source_file"] for doc in docs] == ["novos/b.txt"]
    assert not (tmp_path / "documents").exists()


def test_cache_incremental_substitui_alterados_e_remove_excluidos():
    cached = [
        TextNode(text="A", metadata={"source_file": "a.txt"}),
        TextNode(text="B antigo", metadata={"source_file": "b.txt"}),
        TextNode(text="C", metadata={"source_file": "c.txt"}),
    ]
    replacement = TextNode(text="B novo", metadata={"source_file": "b.txt"})

    merged = merge_nodes_cache(cached, ["b.txt", "c.txt"], [replacement])

    assert [(node.metadata["source_file"], node.text) for node in merged] == [
        ("a.txt", "A"),
        ("b.txt", "B novo"),
    ]


def test_sincronizacao_incremental_carrega_apenas_arquivo_novo(tmp_path, monkeypatch):
    import index_sync as sync

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    old_file = data_dir / "antigo.txt"
    new_file = data_dir / "novo.txt"
    old_file.write_text("antigo", encoding="utf-8")
    old_snapshot = data_snapshot(str(data_dir))
    new_file.write_text("novo", encoding="utf-8")

    db_path = tmp_path / "db"
    save_manifest(str(db_path), old_snapshot)
    save_nodes_cache(
        [TextNode(text="antigo", metadata={"source_file": "antigo.txt"})],
        str(db_path),
    )

    class FakeCollection:
        def count(self):
            return 1

    class FakeClient:
        def get_or_create_collection(self, _name):
            return FakeCollection()

    calls = {}

    def fake_load(data_dir, source_files=None, save_output=True):
        calls["loaded"] = (data_dir, source_files, save_output)
        return [Document(text="novo", metadata={"source_file": "novo.txt", "type": "text"})]

    def fake_process(_docs):
        return [TextNode(text="novo", metadata={"source_file": "novo.txt"})]

    def fake_update(nodes, changed_sources, **_kwargs):
        calls["updated"] = (nodes, changed_sources)
        return "indice"

    monkeypatch.setattr(sync.chromadb, "PersistentClient", lambda path: FakeClient())
    monkeypatch.setattr(sync, "load_documents", fake_load)
    monkeypatch.setattr(sync, "process_documents", fake_process)
    monkeypatch.setattr(sync, "update_index_incrementally", fake_update)

    class Log:
        def info(self, *_args):
            pass

        def warning(self, *_args):
            pass

    index, changed = sync.sync_standard_index(str(data_dir), str(db_path), Log())

    assert index == "indice"
    assert changed == ["novo.txt"]
    assert calls["loaded"] == (str(data_dir), ["novo.txt"], False)
    assert calls["updated"][1] == ["novo.txt"]
    assert load_manifest(str(db_path)) == data_snapshot(str(data_dir))


def test_sincronizacao_incremental_remove_fonte_sem_reler_corpus(tmp_path, monkeypatch):
    import index_sync as sync

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    current = data_dir / "mantido.txt"
    current.write_text("mantido", encoding="utf-8")
    snapshot = data_snapshot(str(data_dir))
    old_manifest = {
        **snapshot,
        "removido.txt": {"mtime_ns": 1, "size": 8},
    }

    db_path = tmp_path / "db"
    save_manifest(str(db_path), old_manifest)
    save_nodes_cache(
        [
            TextNode(text="mantido", metadata={"source_file": "mantido.txt"}),
            TextNode(text="removido", metadata={"source_file": "removido.txt"}),
        ],
        str(db_path),
    )

    class FakeCollection:
        def count(self):
            return 2

    class FakeClient:
        def get_or_create_collection(self, _name):
            return FakeCollection()

    calls = {}

    def fake_update(nodes, changed_sources, **_kwargs):
        calls["updated"] = (nodes, changed_sources)
        return "indice"

    monkeypatch.setattr(sync.chromadb, "PersistentClient", lambda path: FakeClient())
    monkeypatch.setattr(
        sync,
        "load_documents",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("não deve reler")),
    )
    monkeypatch.setattr(sync, "update_index_incrementally", fake_update)

    class Log:
        def info(self, *_args):
            pass

        def warning(self, *_args):
            pass

    index, changed = sync.sync_standard_index(str(data_dir), str(db_path), Log())

    assert index == "indice"
    assert changed == ["removido.txt"]
    assert calls["updated"] == ([], ["removido.txt"])
    assert load_manifest(str(db_path)) == snapshot


def test_indice_portatil_inicia_sem_corpus_e_sem_reindexar(tmp_path, monkeypatch):
    import index_sync as sync

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = tmp_path / "db"
    save_nodes_cache(
        [TextNode(text="conteúdo portátil", metadata={"source_file": "fonte.pdf"})],
        str(db_path),
    )

    class FakeCollection:
        def count(self):
            return 42

    class FakeClient:
        def get_or_create_collection(self, _name):
            return FakeCollection()

    class Log:
        def info(self, *_args):
            pass

        def warning(self, *_args):
            pass

    monkeypatch.setenv("RAG_INDEX_READ_ONLY", "1")
    monkeypatch.setattr(sync.chromadb, "PersistentClient", lambda path: FakeClient())
    monkeypatch.setattr(
        sync,
        "create_or_load_index",
        lambda nodes, **_kwargs: "índice carregado" if nodes == [] else "inválido",
    )
    monkeypatch.setattr(
        sync,
        "load_documents",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("não deve ingerir corpus")
        ),
    )

    index, changed = sync.sync_standard_index(str(data_dir), str(db_path), Log())

    assert index == "índice carregado"
    assert changed == []


def test_serie_anual_numerica_e_valida():
    df = pd.DataFrame({"Ano": [2022, 2023, 2024], "Valor": [1.0, 2.0, 3.0]})
    assert _df_is_valid_timeseries(df)
    node = _Node({"type": "table", "table_granularidade": "anual"})
    assert _is_temporal_table(node)
    assert not _is_static_table(node)


def test_indice_numerico_generico_nao_e_serie_temporal():
    df = pd.DataFrame({"Índice": [0, 1, 2], "Valor": [1.0, 2.0, 3.0]})
    assert not _df_is_valid_timeseries(df)


def test_proveniencia_normaliza_origem_pagina_e_escore():
    leaf = _Node({"source_file": "regional/a.pdf", "page": 3}, score=0.82)
    summary = _Node({"source_files": "a.pdf, b.pdf"}, score=8.2)
    assert source_file(leaf) == "regional/a.pdf"
    assert source_page(leaf) == 3
    assert relevance_score(leaf) == 0.82
    assert source_file(summary) == "a.pdf, b.pdf"
    assert relevance_score(summary) == 0.82


def test_orcamento_de_contexto_e_deterministico():
    text = "a" * 10_000
    limited = limit_context(text, max_tokens=100)
    assert estimate_tokens(limited) <= 110  # inclui o marcador explícito de truncamento
    assert "Contexto truncado" in limited


def test_deterministic_node_ids():
    from processing import _assign_deterministic_ids
    n1 = TextNode(text="Conteúdo de teste", metadata={"source_file": "a.pdf", "page": 1, "type": "text", "chunk_id": 1})
    n2 = TextNode(text="Conteúdo de teste", metadata={"source_file": "a.pdf", "page": 1, "type": "text", "chunk_id": 1})
    _assign_deterministic_ids([n1, n2])
    assert n1.id_ == n2.id_
    assert len(n1.id_) == 32



