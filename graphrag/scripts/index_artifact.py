"""Exportação e instalação de índices portáteis de releases confiáveis.

O cache BM25 contém pickle: use apenas artefatos produzidos pelo próprio projeto.
SHA-256 detecta corrupção, não autentica o publicador.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4

DEFAULT_RELEASE_REPO = ""
DEFAULT_RELEASE_TAG = "index-v1"
DEFAULT_RELEASE_ASSET = "graph-rag-index.tar.gz"
INSTALLED_MANIFEST = "artifact_manifest.json"
_REQUIRED = ("chroma.sqlite3", "bm25_nodes.pkl", "indexed_manifest.json")


class ArtifactError(RuntimeError):
    """Artefato ausente, inválido ou incompatível."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _collection_count(path: Path) -> int:
    import chromadb
    return chromadb.PersistentClient(path=str(path)).get_collection("estatisticas").count()


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def build_artifact(output: Path, *, db_dir: Path):
    """Exporte somente com o servidor parado, para obter um snapshot consistente."""
    output, db_dir = Path(output).resolve(), Path(db_dir).resolve()
    if output.is_relative_to(db_dir):
        raise ArtifactError("O artefato deve ficar fora do banco de origem.")
    if not all((db_dir / name).is_file() for name in _REQUIRED):
        raise ArtifactError("Banco incompleto; exportação cancelada.")
    count = _collection_count(db_dir)
    if count <= 0:
        raise ArtifactError("Banco vazio; exportação cancelada.")
    files = sorted(p for p in db_dir.rglob("*") if p.is_file() and p.name != INSTALLED_MANIFEST)
    if any(p.is_symlink() for p in db_dir.rglob("*")):
        raise ArtifactError("Links não são permitidos no banco exportado.")
    manifest = {
        "schema_version": 1, "vector_count": count,
        "embedding_model": os.getenv("RAG_EMBED_MODEL", "BAAI/bge-m3"),
        "commit": _git_commit(),
        "files": {p.relative_to(db_dir).as_posix(): _sha256(p) for p in files},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        manifest_path = Path(temp) / INSTALLED_MANIFEST
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        staged = Path(temp) / "index.tar.gz"
        with tarfile.open(staged, "w:gz") as archive:
            for path in files:
                archive.add(path, arcname=path.relative_to(db_dir).as_posix(), recursive=False)
            archive.add(manifest_path, arcname=INSTALLED_MANIFEST)
        os.replace(staged, output)
    sidecar = Path(str(output) + ".sha256")
    sidecar.write_text(f"{_sha256(output)}  {output.name}\n", encoding="utf-8")
    return output, sidecar, manifest


def _extract_verified(archive_path: Path, destination: Path) -> dict:
    sidecar = Path(str(archive_path) + ".sha256")
    try:
        expected = sidecar.read_text(encoding="utf-8").split()[0]
    except (OSError, IndexError) as exc:
        raise ArtifactError("SHA-256 externo ausente.") from exc
    if _sha256(archive_path) != expected:
        raise ArtifactError("SHA-256 externo divergente.")
    seen = set()
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive:
            name = member.name
            parts = PurePosixPath(name).parts
            if (not member.isfile() or not parts or name.startswith("/")
                    or "\\" in name or ":" in name or ".." in parts
                    or name in seen):
                raise ArtifactError("Caminho ou tipo inválido no artefato.")
            target = (destination / name).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ArtifactError("Caminho fora do destino.")
            seen.add(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
    try:
        manifest = json.loads((destination / INSTALLED_MANIFEST).read_text(encoding="utf-8"))
        hashes = manifest["files"]
        if manifest["schema_version"] != 1 or int(manifest["vector_count"]) <= 0:
            raise ValueError("versão/contagem")
        if set(hashes) != seen - {INSTALLED_MANIFEST} or not set(_REQUIRED) <= set(hashes):
            raise ValueError("lista de arquivos")
        for name, expected_hash in hashes.items():
            if _sha256(destination / name) != expected_hash:
                raise ValueError("SHA-256 interno")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ArtifactError("Manifesto ou SHA-256 interno inválido.") from exc
    return manifest


def verify_artifact(archive: Path) -> dict:
    with tempfile.TemporaryDirectory() as temp:
        return _extract_verified(Path(archive), Path(temp))


def install_artifact(archive: Path, *, target: Path, backup_root: Path | None = None):
    target = Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    with tempfile.TemporaryDirectory(dir=target.parent) as temp:
        staged = Path(temp) / "index"
        staged.mkdir()
        manifest = _extract_verified(Path(archive), staged)
        # A verificação completa ocorre antes de mover qualquer banco existente.
        if target.exists():
            root = Path(backup_root).resolve() if backup_root else target.parent
            if root == target or root.is_relative_to(target):
                raise ArtifactError("Backup deve ficar fora do banco de destino.")
            root.mkdir(parents=True, exist_ok=True)
            backup = root / f"{target.name}.backup-{uuid4().hex}"
            target.rename(backup)
        try:
            staged.rename(target)
        except OSError:
            if backup is not None:
                backup.rename(target)
            raise
    return manifest, backup


def _release_asset_url(repo: str, tag: str, asset: str) -> str:
    parts = repo.split("/")
    if len(parts) != 2 or not all(parts) or any(p in {".", ".."} for p in parts):
        raise ArtifactError("Defina RAG_INDEX_REPO como proprietário/repositório.")
    encoded_repo = "/".join(quote(p, safe="") for p in parts)
    return f"https://github.com/{encoded_repo}/releases/download/{quote(tag, safe='')}/{quote(asset, safe='')}"


def _download_file(url: str, destination: Path, *, token=None, timeout=600):
    # Token não é enviado a URLs públicas que redirecionam para outro domínio.
    if token:
        raise ArtifactError("Download autenticado não suportado; instale o artefato localmente.")
    with urlopen(Request(url), timeout=timeout) as response, Path(destination).open("wb") as output:
        shutil.copyfileobj(response, output)


def ensure_release_index(*, target: Path, repo=DEFAULT_RELEASE_REPO,
                         tag=DEFAULT_RELEASE_TAG, asset=DEFAULT_RELEASE_ASSET,
                         token=None, timeout=600):
    target = Path(target)
    if target.exists() and any(target.iterdir()):
        if not all((target / name).is_file() for name in _REQUIRED):
            raise ArtifactError("Banco incompleto; instalação automática cancelada.")
        count = _collection_count(target)
        if count <= 0:
            raise ArtifactError("Banco incompleto ou vazio.")
        return count, False
    url = _release_asset_url(repo, tag, asset)
    with tempfile.TemporaryDirectory() as temp:
        archive = Path(temp) / "index.tar.gz"
        _download_file(url, archive, token=token, timeout=timeout)
        _download_file(url + ".sha256", Path(str(archive) + ".sha256"), token=token, timeout=timeout)
        manifest, _ = install_artifact(archive, target=target)
    return manifest["vector_count"], True
