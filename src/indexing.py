import os
import pickle
import time
import chromadb
from llama_index.core import VectorStoreIndex, StorageContext
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.core import Settings
from logger import get_logger

log = get_logger(__name__)

_NODES_CACHE_NAME = "bm25_nodes.pkl"
_EMBED_INSTANCE = None
_EMBED_IDENTITY = None

def _nodes_cache_path(db_path: str) -> str:
    return os.path.join(db_path, _NODES_CACHE_NAME)

def save_nodes_cache(nodes, db_path="./chroma_db"):
    os.makedirs(db_path, exist_ok=True)
    path = _nodes_cache_path(db_path)
    temporary = path + ".tmp"
    with open(temporary, "wb") as f:
        pickle.dump(nodes, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)

def load_nodes_cache(db_path="./chroma_db"):
    path = _nodes_cache_path(db_path)
    if os.path.exists(path):
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except (OSError, EOFError, pickle.UnpicklingError):
            return []
    return []

def reset_nodes_cache(db_path="./chroma_db"):
    """Remove o cache lexical quando o índice vetorial é reconstruído do zero."""
    path = _nodes_cache_path(db_path)
    if os.path.exists(path):
        os.remove(path)

def merge_nodes_cache(cached_nodes, changed_sources, new_nodes):
    """Substitui no cache somente nós pertencentes às fontes alteradas."""
    changed = set(changed_sources)
    retained = [
        node for node in cached_nodes
        if node.metadata.get("source_file") not in changed
    ]
    return retained + list(new_nodes)

def _node_ids_for_sources(collection, source_files):
    """Captura IDs atuais antes da inserção dos nós substitutos."""
    ids: list[str] = []
    for source_file in source_files:
        result = collection.get(where={"source_file": source_file})
        ids.extend(result.get("ids") or [])
    return ids

def _delete_ids(collection, ids, batch_size=1000):
    for start in range(0, len(ids), batch_size):
        collection.delete(ids=ids[start:start + batch_size])

def _embed_config() -> dict:
    """Config formal do embedding local (bge-m3), com batch/device/normalização explícitos."""
    from runtime import bounded_int
    return {
        "provider": os.getenv("RAG_EMBED_PROVIDER", "huggingface").strip().lower(),
        "model": os.getenv("RAG_EMBED_MODEL", "BAAI/bge-m3").strip() or "BAAI/bge-m3",
        "batch_size": bounded_int("RAG_EMBED_BATCH_SIZE", 16, 1, 128),
        "device": os.getenv("RAG_EMBED_DEVICE", "auto").strip().lower() or "auto",
        "normalize": os.getenv("RAG_EMBED_NORMALIZE", "1").strip().lower() in {"1", "true", "yes", "on"},
        "max_length": bounded_int("RAG_EMBED_MAX_LENGTH", 8192, 512, 8192),
        "write_batch": bounded_int("RAG_CHROMA_WRITE_BATCH_SIZE", 256, 16, 2048),
    }



def _insert_nodes_in_batches(index, nodes):
    """Persiste blocos em lotes e registra o avanço da vetorização."""
    batch_size = _embed_config()["write_batch"]
    total = len(nodes)
    started = time.monotonic()
    for start in range(0, total, batch_size):
        batch = nodes[start:start + batch_size]
        index.insert_nodes(batch)
        completed = start + len(batch)
        rate = completed / max(time.monotonic() - started, 0.001)
        log.info(
            "Embeddings: %d/%d blocos (%.1f%%), %.2f blocos/s, restante estimado %.1f min",
            completed, total, 100 * completed / total, rate,
            (total - completed) / rate / 60,
        )


def setup_embeddings():
    """Seleciona um modelo local, compartilhado entre indexação e consulta."""
    global _EMBED_INSTANCE, _EMBED_IDENTITY
    cfg = _embed_config()
    if cfg["provider"] == "ollama":
        from pathlib import Path
        from ollama_embeddings import CachedOllamaEmbedding, resolve_model_digest
        url = os.getenv("RAG_OLLAMA_EMBED_URL", "http://127.0.0.1:11434").rstrip("/")
        digest = resolve_model_digest(url, cfg["model"])
        os.environ["RAG_EMBED_MODEL_REVISION"] = digest
        cache_path = os.getenv("RAG_EMBED_CACHE_PATH", str(Path(__file__).resolve().parents[1] / ".cache" / "embeddings.sqlite3"))
        identity = (cfg["provider"], cfg["model"], digest, url, cache_path, cfg["batch_size"])
        if identity != _EMBED_IDENTITY:
            model = CachedOllamaEmbedding(
                model_name=cfg["model"], model_digest=digest, base_url=url,
                cache_path=cache_path, embed_batch_size=cfg["batch_size"],
            )
            model.get_text_embedding("validação de dimensão")
            _EMBED_INSTANCE, _EMBED_IDENTITY = model, identity
    elif cfg["provider"] == "huggingface":
        os.environ.pop("RAG_EMBED_MODEL_REVISION", None)
        identity = tuple(sorted(cfg.items()))
        if identity != _EMBED_IDENTITY:
            from llama_index.embeddings.huggingface import HuggingFaceEmbedding
            kwargs = {"model_name": cfg["model"], "embed_batch_size": cfg["batch_size"],
                      "max_length": cfg["max_length"], "normalize": cfg["normalize"]}
            if cfg["device"] in {"cpu", "cuda"}:
                kwargs["device"] = cfg["device"]
            _EMBED_INSTANCE = HuggingFaceEmbedding(**kwargs)
            _EMBED_IDENTITY = identity
    else:
        raise ValueError("RAG_EMBED_PROVIDER deve ser huggingface ou ollama.")
    Settings.embed_model = _EMBED_INSTANCE
    log.info("Embeddings locais: provider=%s, model=%s, batch=%d", cfg["provider"], cfg["model"], cfg["batch_size"])
    return _EMBED_INSTANCE


def validate_embedding_compat(db_path: str, collection_name: str = "estatisticas") -> None:
    """Aborta boot se dimensão/modelo persistido divergir do runtime (evita servir vetores incompatíveis)."""
    from pathlib import Path
    import json
    manifest_path = Path(db_path) / "indexed_manifest.json"
    if not manifest_path.exists():
        return
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(data, dict) or data.get("schema_version") != 2:
        return
    pipe = data.get("pipeline", {}) or {}
    want_model = os.getenv("RAG_EMBED_MODEL", "BAAI/bge-m3").strip() or "BAAI/bge-m3"
    got_model = str(pipe.get("embed_model", want_model))
    if got_model != want_model:
        raise RuntimeError(
            f"Modelo de embedding incompatível: índice usa '{got_model}', runtime pede '{want_model}'. "
            f"Faça full rebuild (apague {db_path} ou ajuste RAG_EMBED_MODEL)."
        )
    if pipe.get("embed_provider", "huggingface") != os.getenv("RAG_EMBED_PROVIDER", "huggingface"):
        raise RuntimeError("Provedor de embeddings incompatível com o índice; reconstrua-o.")
    if pipe.get("embed_revision", "") != os.getenv("RAG_EMBED_MODEL_REVISION", ""):
        raise RuntimeError("Revisão do modelo incompatível com o índice; reconstrua-o.")
    want_dim = pipe.get("embed_dim")
    if want_dim is None:
        return
    try:
        probe = Settings.embed_model.get_text_embedding("validação de dimensão")
        if len(probe) != int(want_dim):
            raise RuntimeError(
                f"Dimensão de embedding incompatível: índice tem dim={want_dim}, modelo atual gera dim={len(probe)}."
            )
    except RuntimeError:
        raise
    except Exception:
        pass

def create_or_load_index(nodes, db_path="./chroma_db", collection_name="estatisticas"):
    """
    Cria um VectorStore Persistente via ChromaDB local, permitindo reutilizar o banco entre sessões.
    Implementa Staging & Swap transacional a nível de COLEÇÃO (estatisticas__staging -> estatisticas),
    evitando WinError 32 (arquivo em uso no Windows) e corrupção.
    """
    setup_embeddings()

    is_full_build = nodes is not None and len(nodes) > 0
    os.makedirs(db_path, exist_ok=True)
    db = chromadb.PersistentClient(path=db_path)

    staging_name = f"{collection_name}__staging"
    _cosine = {"hnsw:space": "cosine"}

    if is_full_build:
        # Remove staging anterior se órfã
        try:
            db.delete_collection(staging_name)
        except Exception:
            pass

        print(f"Indexando {len(nodes)} blocos processados na coleção staging '{staging_name}'...")
        staging_col = db.get_or_create_collection(staging_name, metadata=_cosine)
        vector_store = ChromaVectorStore(chroma_collection=staging_col)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)

        index = VectorStoreIndex(
            [], storage_context=storage_context,
            insert_batch_size=_embed_config()["write_batch"], show_progress=True,
        )
        _insert_nodes_in_batches(index, nodes)

        # Validação rigorosa antes da promoção
        stg_count = staging_col.count()
        if stg_count != len(nodes):
            db.delete_collection(staging_name)
            raise RuntimeError(
                f"Validação falhou: contagem Chroma staging ({stg_count}) != nós processados ({len(nodes)})"
            )
        try:
            # Smoke query com o próprio modelo (query_texts usaria o EF padrão do Chroma, 384 dims)
            qvec = Settings.embed_model.get_query_embedding("economia estado São Paulo")
            smoke = staging_col.query(query_embeddings=[qvec], n_results=1)
            if not smoke or not smoke.get("ids") or not smoke["ids"][0]:
                log.warning("Smoke query retornou vazio na staging — prosseguindo com cautela")
        except Exception as sq_exc:
            db.delete_collection(staging_name)
            raise RuntimeError(f"Smoke query falhou na validação da staging: {sq_exc}") from sq_exc

        try:
            from faiss_store import faiss_enabled, build_faiss_index
            if faiss_enabled():
                build_faiss_index(nodes, db_path)
        except Exception:
            pass

        # Atomic Swap de Coleção
        try:
            db.delete_collection(collection_name)
        except Exception:
            pass

        staging_col.modify(name=collection_name)
        print(f"Coleção '{collection_name}' promovida com sucesso via swap atômico.")

        # Salva cache BM25 somente após promoção bem-sucedida
        save_nodes_cache(nodes, db_path=db_path)
        print(f"Cache BM25 salvo em {_nodes_cache_path(db_path)}")

        # Reabre no target oficial
        chroma_collection = db.get_or_create_collection(collection_name, metadata=_cosine)
        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex.from_vector_store(
            vector_store, storage_context=storage_context,
            insert_batch_size=_embed_config()["write_batch"], show_progress=True,
        )
    else:
        print("Carregando conhecimento a partir do banco de dados vetorial já populado...")
        chroma_collection = db.get_or_create_collection(collection_name, metadata=_cosine)
        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex.from_vector_store(
            vector_store,
            storage_context=storage_context
        )

    return index

def update_index_incrementally(
    nodes,
    changed_sources,
    db_path="./chroma_db",
    collection_name="estatisticas",
):
    """Insere substitutos e só depois remove IDs antigos das fontes alteradas."""
    nodes = list(nodes)
    setup_embeddings()

    db = chromadb.PersistentClient(path=db_path)
    collection = db.get_or_create_collection(collection_name)
    stale_ids = _node_ids_for_sources(collection, changed_sources)

    vector_store = ChromaVectorStore(chroma_collection=collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    index = VectorStoreIndex.from_vector_store(
        vector_store,
        storage_context=storage_context,
        insert_batch_size=_embed_config()["write_batch"], show_progress=True,
    )

    old_ids = set(stale_ids)
    new_nodes = [node for node in nodes if node.node_id not in old_ids]
    if new_nodes:
        print(f"Indexando incrementalmente {len(new_nodes)} bloco(s) novo(s)/alterado(s)...")
        _insert_nodes_in_batches(index, new_nodes)

    replacement_ids = {node.node_id for node in nodes}
    # IDs determinísticos podem ser compartilhados com trechos preservados.
    _delete_ids(collection, [nid for nid in stale_ids if nid not in replacement_ids])

    cached_nodes = load_nodes_cache(db_path)
    file_changed = [s for s in (changed_sources or []) if not str(s).startswith("__")]
    merged_nodes = merge_nodes_cache(cached_nodes, file_changed, nodes)
    save_nodes_cache(merged_nodes, db_path=db_path)
    print(
        f"Atualização incremental concluída: {len(stale_ids)} bloco(s) antigo(s) "
        f"removido(s), {len(nodes)} inserido(s)."
    )
    # P3 FAISS opcional — rebuild incremental (simples: reconstrói do merged)
    try:
        from faiss_store import faiss_enabled, build_faiss_index
        if faiss_enabled():
            build_faiss_index(merged_nodes, db_path)
    except Exception:
        pass
    return index


def append_nodes_to_index(nodes, db_path="./chroma_db", collection_name="estatisticas"):
    """Insere nós novos (ex: resumos RAPTOR) sem remover nada; mescla BM25 e salva manifesto parcial."""
    if not nodes:
        return None
    setup_embeddings()
    db = chromadb.PersistentClient(path=db_path)
    collection = db.get_or_create_collection(collection_name, metadata={"hnsw:space": "cosine"})
    vector_store = ChromaVectorStore(chroma_collection=collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    index = VectorStoreIndex.from_vector_store(
        vector_store, storage_context=storage_context,
        insert_batch_size=_embed_config()["write_batch"], show_progress=True,
    )
    print(f"Inserindo {len(nodes)} nó(s) adicional(is) na coleção '{collection_name}'...")
    _insert_nodes_in_batches(index, list(nodes))
    cached_nodes = load_nodes_cache(db_path)
    merged = list(cached_nodes or []) + list(nodes)
    save_nodes_cache(merged, db_path=db_path)
    return index
