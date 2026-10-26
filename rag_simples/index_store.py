"""Persistência e validação do índice JSON do RAG simples."""
import json
from dataclasses import asdict
from pathlib import Path

from rag_simples.documents import Chunk
from rag_simples.vectors import normalize
from rag_app.storage import write_json

VERSION = 2
BACKEND = "huggingface-local"


def save_index(path: Path, chunks: list[Chunk], vectors: list[list[float]], *,
               embedding_model: str, size: int, overlap: int, experiment=None) -> None:
    if len(vectors) != len(chunks) or len({len(v) for v in vectors}) != 1:
        raise ValueError("Embeddings incompatíveis com os trechos dos documentos.")
    write_json(Path(path), {
        "version": VERSION,
        "embedding_backend": BACKEND,
        "embedding_model": embedding_model,
        "chunk_size": size,
        "chunk_overlap": overlap,
        "chunks": [asdict(chunk) for chunk in chunks],
        "vectors": vectors,  # já normalizados pelo chamador
        "experiment": experiment,
    })


def load_index(path: Path, embedding_model: str) -> dict:
    path = Path(path)
    if not path.is_file():
        raise ValueError("Índice não encontrado. Execute primeiro o comando indexar.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        model = payload["embedding_model"]
        chunks, vectors = payload["chunks"], payload["vectors"]
        if (payload["version"] != VERSION or payload.get("embedding_backend") != BACKEND
                or not chunks or len(chunks) != len(vectors)
                or len({len(v) for v in vectors}) != 1):
            raise ValueError("Estrutura inválida.")
        for chunk in chunks:
            Chunk(**chunk)
        payload["vectors"] = [normalize(v) for v in vectors]
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("Índice inválido. Execute indexar novamente.") from exc
    if model != embedding_model:
        raise ValueError("O modelo de embeddings mudou. Execute indexar novamente.")
    return payload
