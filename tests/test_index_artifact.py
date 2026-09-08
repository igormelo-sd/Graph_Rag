"""Testes do artefato portátil usado em GitHub Releases."""
import shutil
from pathlib import Path

import pytest

from scripts import index_artifact


def _fake_db(root: Path) -> Path:
    db = root / "chroma_db"
    segment = db / "segmento-uuid"
    segment.mkdir(parents=True)
    (db / "chroma.sqlite3").write_bytes(b"sqlite-portatil")
    (db / "bm25_nodes.pkl").write_bytes(b"cache-bm25")
    (db / "indexed_manifest.json").write_text("{}", encoding="utf-8")
    (segment / "data_level0.bin").write_bytes(b"vetores")
    return db


def test_exporta_verifica_e_instala_com_backup(tmp_path, monkeypatch):
    source_db = _fake_db(tmp_path / "origem")
    archive = tmp_path / "artefatos" / "indice.tar.gz"
    monkeypatch.setattr(index_artifact, "_collection_count", lambda *_args: 7)
    monkeypatch.setattr(index_artifact, "_git_commit", lambda: "abc123")

    output, sidecar, exported = index_artifact.build_artifact(
        archive,
        db_dir=source_db,
    )

    assert output == archive
    assert sidecar.is_file()
    assert exported["vector_count"] == 7
    assert exported["embedding_model"] == "BAAI/bge-m3"
    assert index_artifact.verify_artifact(archive)["vector_count"] == 7

    target = tmp_path / "destino" / "chroma_db"
    target.mkdir(parents=True)
    (target / "antigo.txt").write_text("preservar", encoding="utf-8")
    manifest, backup = index_artifact.install_artifact(
        archive,
        target=target,
        backup_root=tmp_path / "backups",
    )

    assert manifest["vector_count"] == 7
    assert (target / "chroma.sqlite3").read_bytes() == b"sqlite-portatil"
    assert (target / index_artifact.INSTALLED_MANIFEST).is_file()
    assert backup is not None
    assert (backup / "antigo.txt").read_text(encoding="utf-8") == "preservar"


def test_checksum_externo_corrompido_e_rejeitado(tmp_path, monkeypatch):
    source_db = _fake_db(tmp_path / "origem")
    archive = tmp_path / "indice.tar.gz"
    monkeypatch.setattr(index_artifact, "_collection_count", lambda *_args: 3)
    monkeypatch.setattr(index_artifact, "_git_commit", lambda: "abc123")
    _output, sidecar, _manifest = index_artifact.build_artifact(
        archive,
        db_dir=source_db,
    )
    sidecar.write_text(f"{'0' * 64}  {archive.name}\n", encoding="utf-8")

    with pytest.raises(index_artifact.ArtifactError, match="SHA-256"):
        index_artifact.verify_artifact(archive)


def test_bootstrap_reutiliza_banco_local_valido(tmp_path, monkeypatch):
    target = _fake_db(tmp_path)
    monkeypatch.setattr(index_artifact, "_collection_count", lambda *_args: 16_237)

    def unexpected_download(*_args, **_kwargs):
        raise AssertionError("não deveria baixar banco existente")

    monkeypatch.setattr(index_artifact, "_download_file", unexpected_download)

    count, downloaded = index_artifact.ensure_release_index(target=target)

    assert count == 16_237
    assert downloaded is False


def test_bootstrap_baixa_valida_e_instala_uma_vez(tmp_path, monkeypatch):
    source_db = _fake_db(tmp_path / "origem")
    archive = tmp_path / "release" / index_artifact.DEFAULT_RELEASE_ASSET
    monkeypatch.setattr(index_artifact, "_collection_count", lambda *_args: 16_237)
    monkeypatch.setattr(index_artifact, "_git_commit", lambda: "abc123")
    index_artifact.build_artifact(archive, db_dir=source_db)

    downloads = []

    def fake_download(url, destination, **_kwargs):
        downloads.append(url)
        source = (
            Path(str(archive) + ".sha256")
            if url.endswith(".sha256")
            else archive
        )
        shutil.copy2(source, destination)

    monkeypatch.setattr(index_artifact, "_download_file", fake_download)
    target = tmp_path / "destino" / "chroma_db"
    target.mkdir(parents=True)

    count, downloaded = index_artifact.ensure_release_index(target=target)
    second_count, second_downloaded = index_artifact.ensure_release_index(target=target)

    assert count == second_count == 16_237
    assert downloaded is True
    assert second_downloaded is False
    assert len(downloads) == 2
    assert (target / index_artifact.INSTALLED_MANIFEST).is_file()


def test_bootstrap_nao_sobrescreve_banco_parcial(tmp_path, monkeypatch):
    target = tmp_path / "chroma_db"
    target.mkdir()
    (target / "chroma.sqlite3").write_bytes(b"incompleto")

    def unexpected_download(*_args, **_kwargs):
        raise AssertionError("banco parcial não deve ser sobrescrito")

    monkeypatch.setattr(index_artifact, "_download_file", unexpected_download)

    with pytest.raises(index_artifact.ArtifactError, match="Banco incompleto"):
        index_artifact.ensure_release_index(target=target)


def test_url_da_release_escapa_tag_e_asset():
    url = index_artifact._release_asset_url(
        "owner/repo",
        "versão 1",
        "índice principal.tar.gz",
    )

    assert url == (
        "https://github.com/owner/repo/releases/download/"
        "vers%C3%A3o%201/%C3%ADndice%20principal.tar.gz"
    )


def test_startup_principal_ativa_bootstrap_sem_forcar_leitura(tmp_path, monkeypatch):
    from rag_principal.src import startup

    captured = {}

    def fake_ensure(**kwargs):
        captured.update(kwargs)
        return 16_237, True

    monkeypatch.delenv("RAG_INDEX_READ_ONLY", raising=False)
    monkeypatch.setattr(startup, "ensure_release_index", fake_ensure)

    startup.ensure_principal_index(str(tmp_path / "chroma_db"))

    assert captured["repo"] == index_artifact.DEFAULT_RELEASE_REPO
    assert captured["tag"] == index_artifact.DEFAULT_RELEASE_TAG
    assert captured["asset"] == index_artifact.DEFAULT_RELEASE_ASSET
    assert captured["target"] == tmp_path / "chroma_db"
    # Download e modo de operação são independentes: bootstrap não força READ_ONLY
    assert "RAG_INDEX_READ_ONLY" not in startup.os.environ


def test_startup_principal_permite_desativar_bootstrap(tmp_path, monkeypatch):
    from rag_principal.src import startup

    monkeypatch.setenv("RAG_INDEX_AUTO_DOWNLOAD", "0")

    def unexpected_bootstrap(**_kwargs):
        raise AssertionError("bootstrap deveria estar desativado")

    monkeypatch.setattr(startup, "ensure_release_index", unexpected_bootstrap)

    startup.ensure_principal_index(str(tmp_path / "chroma_db"))
