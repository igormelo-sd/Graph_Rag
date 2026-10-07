"""Snapshot compartilhado dos documentos usados na indexação.

O snapshot usa caminhos relativos, tamanho e ``mtime_ns``. Assim, mudanças em
subdiretórios e arquivos removidos também invalidam o índice, sem ler o conteúdo
inteiro de todos os documentos em cada inicialização.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

SUPPORTED_EXTENSIONS = {".pdf", ".csv", ".xlsx", ".xls", ".txt"}
_MANIFEST_NAME = "indexed_manifest.json"


def _pipeline_fingerprint() -> str:
    """Hash de versão do pipeline (chunk/embedding/visão/RAPTOR) para invalidar índice quando config muda."""
    from domain_ontology import fingerprint
    # Ativação em consulta não muda os embeddings: metadados ontológicos são excluídos.
    parts = [
        fingerprint(),
        os.getenv("RAG_CHUNK_SIZE", "1024"),
        os.getenv("RAG_CHUNK_OVERLAP", "200"),
        os.getenv("RAG_EMBED_MODEL", "BAAI/bge-m3"),
        os.getenv("RAG_SMALL_TABLE_MAX_ROWS", "10"),
        os.getenv("RAG_VISION", "0"),
        os.getenv("RAG_VISION_MODEL", "qwen2.5vl:7b"),
        os.getenv("RAG_RAPTOR_ENABLE", "0"),
        os.getenv("RAG_RAPTOR_MAX_LEVELS", "3"),
        os.getenv("RAG_RAPTOR_MIN_CLUSTER", "4"),
        os.getenv("RAG_INGEST_LLM_ENRICHMENT", "0"),
        "v4-section-sentence-boundaries",
        "v5-spreadsheet-literal-encoding-merged-headers",
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]


def _file_sha256(path: Path, limit_mb: int = 8) -> str:
    """SHA256 dos primeiros limit_mb MB (suficiente para detectar mudança sem ler 50MB)."""
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            read = 0
            limit = limit_mb * 1024 * 1024
            while chunk := f.read(8192):
                h.update(chunk)
                read += len(chunk)
                if read >= limit:
                    break
        return h.hexdigest()[:16]
    except Exception:
        return ""


def resolve_data_dir(base_dir: str, data_dir: str | None = None) -> str:
    """Resolve a base documental sem depender do diretório de execução.

    Em containers, os documentos ficam normalmente em ``<engine>/data``. Na
    execução local do monorepo, a base compartilhada fica em ``../data``. Um
    caminho explícito sempre tem precedência; entre os defaults, escolhemos o
    primeiro que realmente contém documentos suportados.
    """
    if data_dir:
        return str(Path(data_dir).expanduser().resolve())

    configured = os.getenv("RAG_DATA_DIR")
    if configured:
        return str(Path(configured).expanduser().resolve())

    engine_dir = Path(base_dir).resolve() / "data"
    shared_dir = Path(base_dir).resolve().parent / "data"
    repo_dir = Path(base_dir).resolve().parent.parent / "data"
    for candidate in (engine_dir, shared_dir, repo_dir):
        snap = data_snapshot(str(candidate))
        # precisa ter ao menos 1 arquivo além de __pipeline
        if len([k for k in snap if k != "__pipeline"]) > 0:
            return str(candidate)
    return str(engine_dir)


def resolve_db_dir(base_dir: str, db_dir: str | None = None) -> str:
    """Resolve o ChromaDB, permitindo isolar corpus por variável de ambiente.

    Um caminho explícito tem precedência sobre ``RAG_DB_DIR``. Sem ambos,
    preserva o comportamento anterior em ``<engine>/chroma_db``.
    """
    configured = db_dir or os.getenv("RAG_DB_DIR")
    if configured:
        return str(Path(configured).expanduser().resolve())
    return str(Path(base_dir).resolve() / "chroma_db")


def data_snapshot(data_dir: str) -> dict[str, dict]:
    root = Path(data_dir)
    if not root.is_dir():
        return {"__pipeline": _pipeline_fingerprint()}

    snapshot: dict[str, dict] = {"__pipeline": _pipeline_fingerprint()}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        stat = path.stat()
        relative = path.relative_to(root).as_posix()
        snapshot[relative] = {
            "mtime_ns": stat.st_mtime_ns,
            "size": stat.st_size,
            "sha256": _file_sha256(path),
        }
    return snapshot


def load_manifest(db_path: str) -> dict:
    path = Path(db_path) / _MANIFEST_NAME
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return {}
        if data.get("schema_version") == 2:
            pipeline = data.get("pipeline", {})
            if pipeline.get("fingerprint") != _pipeline_fingerprint():
                return {}
            docs = data.get("documents", {})
            if isinstance(docs, dict):
                docs["__pipeline"] = pipeline.get("fingerprint", _pipeline_fingerprint())
                return docs
            return {}
        else:
            if data.get("__pipeline") != _pipeline_fingerprint():
                return {}
            return data
    except (OSError, json.JSONDecodeError):
        return {}


def save_manifest(db_path: str, snapshot: dict) -> None:
    os.makedirs(db_path, exist_ok=True)
    path = Path(db_path) / _MANIFEST_NAME
    temporary = path.with_suffix(path.suffix + ".tmp")

    pipeline_fp = snapshot.get("__pipeline") if isinstance(snapshot, dict) else None
    if not pipeline_fp:
        pipeline_fp = _pipeline_fingerprint()

    docs = {k: v for k, v in snapshot.items() if not k.startswith("__")} if isinstance(snapshot, dict) else snapshot

    payload = {
        "schema_version": 2,
        "pipeline": {
            "fingerprint": pipeline_fp,
            "chunk_size": os.getenv("RAG_CHUNK_SIZE", "1024"),
            "chunk_overlap": os.getenv("RAG_CHUNK_OVERLAP", "200"),
            "embed_model": os.getenv("RAG_EMBED_MODEL", "BAAI/bge-m3"),
            "embed_dim": snapshot.get("__embed_dim") if isinstance(snapshot, dict) else None,
            "vision": os.getenv("RAG_VISION", "0"),
            "raptor": os.getenv("RAG_RAPTOR_ENABLE", "0"),
        },
        "documents": docs,
    }

    lock = None
    try:
        from filelock import FileLock  # type: ignore

        lock = FileLock(str(Path(db_path) / "_manifest.lock"), timeout=10)
        lock.acquire(timeout=10)
    except Exception:
        lock = None
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if lock is not None:
            try:
                lock.release()
            except Exception:
                pass


def detect_changes(snapshot: dict, manifest: dict) -> list[str]:
    """Retorna caminhos adicionados, modificados ou removidos."""
    return sorted(
        path
        for path in set(snapshot) | set(manifest)
        if snapshot.get(path) != manifest.get(path)
    )
