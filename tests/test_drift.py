"""Guarda-rail de espelhamento do `src/` compartilhado entre as 4 variantes.

As variantes (principal/agentic/raptor/selfrag) espelham o mesmo `src/`.
Este teste garante que os arquivos comuns permaneçam idênticos, evitando drift
silencioso (regra 1 do `RAGs/AGENTS.md`).

Ficam de fora desta lista os arquivos com diferenças intencionais por engine
(`startup.py`, `api.py` e as engines exclusivas `*_engine.py`).
"""
from pathlib import Path

_RAG_ROOT = Path(__file__).resolve().parents[2]  # RAGs/

# Arquivos que devem ser cópias idênticas nas 4 variantes.
SHARED_FILES = [
    "api_models.py",
    "llm.py",
    "metrics.py",
    "answer_policy.py",
    "api_security.py",
    "processing.py",
    "text_retriever.py",
    "tables_retriever.py",
    "timeseries_retriever.py",
    "images_retriever.py",
    "numerical_validator.py",
    "safe_exec.py",
    "indexing.py",
    "ingestion.py",
    "index_sync.py",
    "index_manifest.py",
    "faiss_store.py",
    "usage_tracker.py",
    "graph_indexing.py",
    "graph_retriever.py",
    "graph_ontology.py",
]

VARIANTS = ["agentic", "raptor", "selfrag"]


def _path(variant: str, filename: str) -> Path:
    return _RAG_ROOT / f"rag_{variant}" / "src" / filename


def test_arquivos_compartilhados_identicos_nas_4_variantes():
    for filename in SHARED_FILES:
        base = _path("principal", filename).read_bytes()
        for variant in VARIANTS:
            assert _path(variant, filename).read_bytes() == base, (
                f"Drift detectado: rag_{variant}/src/{filename} difere de rag_principal."
            )