import os
import pickle
import chromadb
from llama_index.core import VectorStoreIndex, StorageContext
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.core import Settings
from logger import get_logger

log = get_logger(__name__)

_NODES_CACHE_NAME = "bm25_nodes.pkl"

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
        "model": os.getenv("RAG_EMBED_MODEL", "BAAI/bge-m3").strip() or "BAAI/bge-m3",
        "batch_size": bounded_int("RAG_EMBED_BATCH_SIZE", 16, 1, 128),
        "device": os.getenv("RAG_EMBED_DEVICE", "auto").strip().lower() or "auto",
        "normalize": os.getenv("RAG_EMBED_NORMALIZE", "1").strip().lower() in {"1", "true", "yes", "on"},
        "max_length": bounded_int("RAG_EMBED_MAX_LENGTH", 8192, 512, 8192),
        "write_batch": bounded_int("RAG_CHROMA_WRITE_BATCH_SIZE", 256, 16, 2048),
    }


def setup_embeddings():
    """
    Configura Embeddings Locais (HuggingFace) para não enviar dados sensíveis p/ nuvem na vetorização.
    Modelo default BAAI/bge-m3; parametrizável via RAG_EMBED_MODEL para tuning.
    """
    cfg = _embed_config()
    print(f"Configurando modelo de embeddings local ({cfg['model']}, batch={cfg['batch_size']}, device={cfg['device']}) ...")
    kwargs: dict = {"model_name": cfg["model"], "embed_batch_size": cfg["batch_size"], "max_length": cfg["max_length"]}
    if cfg["device"] in {"cpu", "cuda"}:
        kwargs["device"] = cfg["device"]
    if not cfg["normalize"]:
        kwargs["normalize_embeddings"] = False
    embed_model = HuggingFaceEmbedding(**kwargs)
    Settings.embed_model = embed_model
    return embed_model


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

        index = VectorStoreIndex(nodes, storage_context=storage_context)

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
        index = VectorStoreIndex.from_vector_store(vector_store, storage_context=storage_context)
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
    setup_embeddings()

    db = chromadb.PersistentClient(path=db_path)
    collection = db.get_or_create_collection(collection_name)
    stale_ids = _node_ids_for_sources(collection, changed_sources)

    vector_store = ChromaVectorStore(chroma_collection=collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    index = VectorStoreIndex.from_vector_store(
        vector_store,
        storage_context=storage_context,
    )

    if nodes:
        print(f"Indexando incrementalmente {len(nodes)} bloco(s) novo(s)/alterado(s)...")
        index.insert_nodes(list(nodes))

    _delete_ids(collection, stale_ids)

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
    index = VectorStoreIndex.from_vector_store(vector_store, storage_context=storage_context)
    print(f"Inserindo {len(nodes)} nó(s) adicional(is) na coleção '{collection_name}'...")
    index.insert_nodes(list(nodes))
    cached_nodes = load_nodes_cache(db_path)
    merged = list(cached_nodes or []) + list(nodes)
    save_nodes_cache(merged, db_path=db_path)
    return index
