"""
faiss_store — índice FAISS opcional (P3) para semente ANN rápida.

Port do kg-web-platform rag_system.py: FAISS FlatIP(1536) + Chroma dual.
Aqui usa bge-m3 (1024 dims) local, atrás de RAG_FAISS=1. Quando desabilitado,
nenhum arquivo é criado e o retrieval permanece Chroma+BM25 (default).

Arquivos: {db_path}/faiss.index + faiss_map.json , rebuild quando nodes mudam
ou pipeline fingerprint muda (via force_rebuild).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from logger import get_logger

log = get_logger(__name__)

_FAISS_INDEX = "faiss.index"
_FAISS_MAP = "faiss_map.json"

def faiss_enabled() -> bool:
    return os.getenv("RAG_FAISS", "0").strip().lower() in {"1", "true", "yes", "on"}

def _faiss_paths(db_path: str) -> tuple[Path, Path]:
    base = Path(db_path)
    return base / _FAISS_INDEX, base / _FAISS_MAP

def build_faiss_index(nodes: list, db_path: str, embed_model=None) -> bool:
    """Constrói faiss.index a partir de nodes (texto). Retorna True se ok."""
    if not faiss_enabled():
        return False
    if not nodes:
        log.info("[FAISS] Sem nós — índice não criado")
        return False
    try:
        import faiss  # type: ignore
        import numpy as np
    except ImportError:
        log.warning("[FAISS] faiss-cpu não instalado — desabilitando (pip install faiss-cpu)")
        return False
    try:
        from llama_index.core import Settings
        model = embed_model or getattr(Settings, "embed_model", None)
        if model is None:
            from indexing import setup_embeddings
            model = setup_embeddings()
        texts = []
        ids = []
        for n in nodes:
            t = getattr(n, "text", "") or getattr(getattr(n, "node", None), "text", "") or ""
            if t.strip():
                texts.append(t[:8000])
                md = getattr(n, "metadata", {}) or {}
                ids.append(f"{md.get('source_file','?')}#{md.get('page','?')}#{md.get('chunk_id','?')}#{len(ids)}")
        if not texts:
            return False
        log.info("[FAISS] Codificando %d textos via %s...", len(texts), getattr(model, "model_name", "bge-m3"))
        # bge-m3 via HuggingFaceEmbedding
        vectors = model.get_text_embedding_batch(texts, show_progress=False) if hasattr(model, "get_text_embedding_batch") else [model.get_text_embedding(t) for t in texts]
        arr = np.array(vectors, dtype="float32")
        # normaliza para IP (cos) — como kg faz L2 normalize
        faiss.normalize_L2(arr)
        dim = arr.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(arr)
        idx_path, map_path = _faiss_paths(db_path)
        idx_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(index, str(idx_path))
        map_path.write_text(json.dumps({"ids": ids, "dim": dim, "count": len(ids)}, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("[FAISS] Índice salvo %s (%d vetores, dim=%d)", idx_path, len(ids), dim)
        return True
    except Exception as exc:
        log.warning("[FAISS] falha ao construir (%s)", exc)
        return False

def load_faiss_index(db_path: str):
    """Carrega índice se habilitado e existente, senão None."""
    if not faiss_enabled():
        return None, None
    idx_path, map_path = _faiss_paths(db_path)
    if not idx_path.exists() or not map_path.exists():
        return None, None
    try:
        import faiss
        index = faiss.read_index(str(idx_path))
        mapping = json.loads(map_path.read_text(encoding="utf-8"))
        return index, mapping
    except Exception as exc:
        log.warning("[FAISS] falha ao carregar (%s)", exc)
        return None, None

def search_faiss(query: str, db_path: str, top_k: int = 5, embed_model=None) -> list[int]:
    """Busca sementes FAISS para query. Retorna índices (posições) ou []."""
    index, mapping = load_faiss_index(db_path)
    if index is None:
        return []
    try:
        import faiss
        import numpy as np
        from llama_index.core import Settings
        model = embed_model or getattr(Settings, "embed_model", None)
        if model is None:
            return []
        qvec = np.array([model.get_query_embedding(query)], dtype="float32")
        faiss.normalize_L2(qvec)
        scores, ids = index.search(qvec, min(top_k, index.ntotal))
        return [int(i) for i in ids[0] if i != -1]
    except Exception as exc:
        log.warning("[FAISS] search falhou (%s)", exc)
        return []
