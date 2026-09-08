"""
debug_embedding.py — Diagnóstico completo do pipeline de embedding.

Executa cada etapa isoladamente e reporta o estado: OK, AVISO ou ERRO.
Não altera nada no índice; apenas lê e mede.

Uso (dentro de RAGs/rag_principal/src ou com sys.path configurado):
    python debug_embedding.py [--pdf <arquivo.pdf>] [--fix-manifest]

Flags:
  --pdf <arquivo.pdf>   Testa ingestão de um PDF específico (relativo a data/)
  --fix-manifest        Remove o manifesto corrompido e força full rebuild
  --verbose             Exibe vetores brutos e metadados dos nós
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from pathlib import Path

# ── Path bootstrap ────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_BASE = _HERE.parent  # RAGs/rag_principal/

sys.path.insert(0, str(_HERE))                              # src/
sys.path.insert(0, str(_BASE.parent.parent / ".agents"))   # .agents/
sys.path.insert(0, str(_BASE.parent.parent))

# ── Cores ANSI ────────────────────────────────────────────────────────────────
_OK   = "[OK]     "
_WARN = "[AVISO]  "
_ERR  = "[ERRO]   "
_INFO = "[INFO]   "


def _ok(msg):    print(f"  {_OK}{msg}")
def _warn(msg):  print(f"  {_WARN}{msg}")
def _err(msg):   print(f"  {_ERR}{msg}")
def _info(msg):  print(f"  {_INFO}{msg}")
def _step(title): print(f"\n{'=' * 60}\n  {title}\n{'=' * 60}")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Variáveis de ambiente
# ═══════════════════════════════════════════════════════════════════════════════

def check_env() -> dict:
    _step("1. Variaveis de Ambiente")
    env_keys = {
        "RAG_EMBED_MODEL":            ("BAAI/bge-m3", "Modelo de embedding"),
        "RAG_EMBED_BATCH_SIZE":       ("16",           "Batch de embedding"),
        "RAG_EMBED_DEVICE":           ("auto",         "Device (cpu/cuda/auto)"),
        "RAG_EMBED_NORMALIZE":        ("1",            "Normalizacao L2"),
        "RAG_EMBED_MAX_LENGTH":       ("8192",         "Comprimento max de tokens"),
        "RAG_CHROMA_WRITE_BATCH_SIZE":("256",          "Batch de escrita no Chroma"),
        "RAG_CHUNK_SIZE":             ("1024",         "Chunk size (chars)"),
        "RAG_CHUNK_OVERLAP":          ("200",          "Chunk overlap (chars)"),
        "RAG_INGEST_LLM_ENRICHMENT":  ("0",            "Enriquecimento LLM na ingestao"),
        "RAG_INDEX_READ_ONLY":        ("0",            "Indice somente leitura"),
        "RAG_DATA_DIR":               (None,           "Dir de dados (opcional)"),
        "RAG_DB_DIR":                 (None,           "Dir do ChromaDB (opcional)"),
    }
    resolved = {}
    for key, (default, desc) in env_keys.items():
        val = os.getenv(key, default or "")
        resolved[key] = val
        if val:
            _ok(f"{key}={val!r}  # {desc}")
        else:
            _warn(f"{key} nao definida (default={default!r})  # {desc}")
    return resolved


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Importações críticas
# ═══════════════════════════════════════════════════════════════════════════════

def check_imports() -> bool:
    _step("2. Importacoes criticas")
    ok = True
    modules = [
        ("llama_index.core",                   "LlamaIndex core"),
        ("llama_index.embeddings.huggingface", "HuggingFace Embedding adapter"),
        ("llama_index.vector_stores.chroma",   "ChromaVectorStore"),
        ("chromadb",                            "ChromaDB client"),
        ("sentence_transformers",               "sentence-transformers (modelo HF)"),
        ("fitz",                                "PyMuPDF (extracao PDF)"),
        ("langchain_text_splitters",            "LangChain text splitter"),
    ]
    for mod, label in modules:
        try:
            __import__(mod)
            _ok(f"{label}  ({mod})")
        except ImportError as exc:
            _err(f"{label}  ({mod})  -> {exc}")
            ok = False

    optional = [
        ("camelot",  "Camelot (tabelas PDF)"),
        ("faiss",    "FAISS (ANN opcional)"),
        ("filelock", "filelock (manifesto seguro)"),
        ("torch",    "PyTorch (GPU/CPU backend)"),
    ]
    for mod, label in optional:
        try:
            __import__(mod)
            _ok(f"{label}  ({mod})  [opcional]")
        except ImportError:
            _warn(f"{label}  ({mod})  nao instalado (opcional)")
    return ok


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Modelo de Embedding
# ═══════════════════════════════════════════════════════════════════════════════

def check_embedding_model() -> tuple:
    """Retorna (embed_model, dim) ou (None, 0)."""
    _step("3. Modelo de Embedding (HuggingFace local)")
    try:
        from indexing import setup_embeddings, _embed_config
        cfg = _embed_config()
        _info(f"Config: model={cfg['model']!r}, batch={cfg['batch_size']}, "
              f"device={cfg['device']!r}, normalize={cfg['normalize']}, "
              f"max_length={cfg['max_length']}")

        t0 = time.perf_counter()
        embed_model = setup_embeddings()
        elapsed = time.perf_counter() - t0
        _ok(f"setup_embeddings() concluido em {elapsed:.2f}s")

        # Smoke test: 1 embedding
        t1 = time.perf_counter()
        vec = embed_model.get_text_embedding("Economia do Estado de Sao Paulo")
        elapsed2 = time.perf_counter() - t1
        dim = len(vec)
        norm = sum(v**2 for v in vec) ** 0.5
        _ok(f"Embedding de teste: dim={dim}, {elapsed2*1000:.1f}ms, norm={norm:.4f}")

        # Batch: 4 textos
        t2 = time.perf_counter()
        batch = embed_model.get_text_embedding_batch([
            "Taxa de desemprego em Sao Paulo",
            "PIB industrial do estado",
            "Exportacoes agropecuarias",
            "Inflacao IPCA mensal",
        ])
        elapsed3 = time.perf_counter() - t2
        _ok(f"Batch 4 embeddings: {elapsed3*1000:.1f}ms ({elapsed3/4*1000:.1f}ms/item)")

        # Similaridade coseno
        v1 = embed_model.get_text_embedding("taxa de desemprego Sao Paulo")
        v2 = embed_model.get_text_embedding("desocupacao no estado de SP")
        dot = sum(a * b for a, b in zip(v1, v2))
        _ok(f"Similaridade coseno (desemprego~desocupacao): {dot:.4f}  (esperado >0.7)")
        if dot < 0.5:
            _warn("Similaridade muito baixa — verifique se o modelo carregou corretamente")

        return embed_model, dim

    except Exception as exc:
        _err(f"Falha ao inicializar embedding: {exc}")
        traceback.print_exc()
        return None, 0


# ═══════════════════════════════════════════════════════════════════════════════
# 4. ChromaDB
# ═══════════════════════════════════════════════════════════════════════════════

def check_chromadb(db_path: str, embed_model, dim: int) -> None:
    _step(f"4. ChromaDB  ->  {db_path}")
    import chromadb as _chromadb

    db = _chromadb.PersistentClient(path=db_path)
    try:
        cols = db.list_collections()
        _ok(f"Colecoes: {[getattr(c, 'name', str(c)) for c in cols]}")
    except Exception as exc:
        _err(f"Erro ao listar colecoes: {exc}")
        return

    collection_name = "estatisticas"
    try:
        col = db.get_or_create_collection(collection_name, metadata={"hnsw:space": "cosine"})
        count = col.count()
        _ok(f"Colecao '{collection_name}': {count} vetores")

        if count > 0:
            peek = col.peek(limit=3)
            ids   = peek.get("ids", [])
            metas = peek.get("metadatas", [])
            docs  = peek.get("documents", []) or []
            for i, (cid, meta, doc) in enumerate(zip(ids, metas, docs)):
                src   = (meta or {}).get("source_file", "?")
                pg    = (meta or {}).get("page", "?")
                ntype = (meta or {}).get("type", "?")
                preview = (doc or "")[:80].replace("\n", " ")
                _info(f"  No {i+1}: id={cid[:12]}... src={src} p={pg} type={ntype} | {preview!r}")

        if count > 0 and embed_model is not None:
            qvec = embed_model.get_query_embedding("taxa de desemprego Sao Paulo")
            if dim > 0 and len(qvec) != dim:
                _err(f"Dimensao query ({len(qvec)}) != dim do modelo ({dim}) — incompatibilidade!")
            else:
                t0 = time.perf_counter()
                res = col.query(query_embeddings=[qvec], n_results=min(3, count))
                elapsed = time.perf_counter() - t0
                ids_r = res.get("ids", [[]])[0]
                dists = res.get("distances", [[]])[0]
                _ok(f"Query smoke: {len(ids_r)} resultado(s) em {elapsed*1000:.1f}ms")
                for rid, dist in zip(ids_r, dists):
                    _info(f"    id={rid[:12]}...  dist={dist:.4f}")

    except Exception as exc:
        _err(f"Erro no ChromaDB: {exc}")
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Manifesto e Snapshot
# ═══════════════════════════════════════════════════════════════════════════════

def check_manifest(db_path: str, data_dir: str) -> list:
    _step(f"5. Manifesto  ->  db={db_path}  data={data_dir}")
    try:
        from index_manifest import data_snapshot, load_manifest, detect_changes, _pipeline_fingerprint

        snapshot = data_snapshot(data_dir)
        fp = _pipeline_fingerprint()
        n_docs = len([k for k in snapshot if k != "__pipeline"])
        _ok(f"Snapshot: {n_docs} arquivo(s), fingerprint={fp!r}")

        manifest = load_manifest(db_path)
        if not manifest:
            _warn("Manifesto vazio ou ausente (first boot ou fingerprint mudou)")
        else:
            n_man = len([k for k in manifest if k != "__pipeline"])
            _ok(f"Manifesto: {n_man} entrada(s)")

        changed = detect_changes(snapshot, manifest)
        file_changes = [c for c in changed if not c.startswith("__")]
        if "__pipeline" in changed:
            _warn("Fingerprint do pipeline mudou -> full rebuild forcado no proximo boot")
        if file_changes:
            _warn(f"Arquivos alterados ({len(file_changes)}): {file_changes[:5]}"
                  + ("..." if len(file_changes) > 5 else ""))
        else:
            _ok("Nenhuma mudanca de arquivo (corpus sincronizado)")
        return changed
    except Exception as exc:
        _err(f"Falha no manifesto: {exc}")
        traceback.print_exc()
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Cache BM25
# ═══════════════════════════════════════════════════════════════════════════════

def check_bm25_cache(db_path: str) -> None:
    _step(f"6. Cache BM25  ->  {db_path}")
    try:
        from indexing import load_nodes_cache, _nodes_cache_path
        path = _nodes_cache_path(db_path)
        if not os.path.exists(path):
            _warn(f"Cache BM25 nao encontrado: {path}")
            return
        size_mb = os.path.getsize(path) / (1024 * 1024)
        _ok(f"Arquivo: {path}  ({size_mb:.2f} MB)")
        nodes = load_nodes_cache(db_path)
        _ok(f"Nos BM25 carregados: {len(nodes)}")
        if nodes:
            sample = nodes[0]
            _info(f"  Amostra: id={getattr(sample, 'id_', '?')[:12]}..."
                  f"  src={sample.metadata.get('source_file','?')}"
                  f"  type={sample.metadata.get('type','?')}"
                  f"  text={sample.text[:40]!r}")
        types = {}
        for n in nodes:
            t = n.metadata.get("type", "text")
            types[t] = types.get(t, 0) + 1
        _info(f"  Distribuicao de tipos: {types}")
    except Exception as exc:
        _err(f"Erro no cache BM25: {exc}")
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Ingestão de amostra
# ═══════════════════════════════════════════════════════════════════════════════

def check_ingest_sample(data_dir: str, pdf_name: str | None = None, verbose: bool = False) -> None:
    _step(f"7. Ingestao de amostra  ->  {data_dir}")
    dp = Path(data_dir)
    if not dp.exists():
        _err(f"Diretorio nao existe: {data_dir}")
        return

    pdfs = sorted(dp.rglob("*.pdf"))
    if not pdfs:
        _warn("Nenhum PDF encontrado em data/")
        return

    if pdf_name:
        target = next((p for p in pdfs if pdf_name in p.name), None)
        if target is None:
            _warn(f"PDF '{pdf_name}' nao encontrado; usando o primeiro")
            target = pdfs[0]
    else:
        target = pdfs[0]

    _info(f"PDF de teste: {target.name}  ({target.stat().st_size / 1024:.1f} KB)")

    try:
        from ingestion import extract_pdf_text, extract_pdf_tables
        t0 = time.perf_counter()
        chunks = extract_pdf_text(target, target.name)
        elapsed = time.perf_counter() - t0
        _ok(f"Texto: {len(chunks)} chunk(s) em {elapsed:.2f}s")
        if chunks and verbose:
            _info(f"  1o chunk: {chunks[0]['text'][:100]!r}")

        t1 = time.perf_counter()
        tables = extract_pdf_tables(target, target.name)
        elapsed2 = time.perf_counter() - t1
        _ok(f"Tabelas: {len(tables)} tabela(s) em {elapsed2:.2f}s")

    except Exception as exc:
        _err(f"Erro na extracao: {exc}")
        traceback.print_exc()
        return

    try:
        from ingestion import to_llama_documents
        from processing import process_documents
        docs = to_llama_documents(chunks, tables)
        _ok(f"Documents criados: {len(docs)}")

        t2 = time.perf_counter()
        nodes = process_documents(docs)
        elapsed3 = time.perf_counter() - t2
        _ok(f"Nos processados: {len(nodes)} em {elapsed3:.2f}s")

        if nodes and verbose:
            n = nodes[0]
            _info(f"  No 0: id={n.id_[:12]}...  text={n.text[:60]!r}  meta={n.metadata}")

    except Exception as exc:
        _err(f"Erro no processamento de nos: {exc}")
        traceback.print_exc()
        return

    # Embedding dos nós de amostra
    try:
        from llama_index.core import Settings
        if Settings.embed_model is None:
            _warn("embed_model nao configurado; pulando embedding de nos")
            return
        texts = [n.text[:512] for n in nodes[:5]]
        t3 = time.perf_counter()
        vecs = Settings.embed_model.get_text_embedding_batch(texts)
        elapsed4 = time.perf_counter() - t3
        _ok(f"Embedding {len(vecs)} no(s): {elapsed4*1000:.1f}ms "
            f"({elapsed4/len(vecs)*1000:.1f}ms/item)  dim={len(vecs[0])}")

    except Exception as exc:
        _err(f"Erro no embedding de nos: {exc}")
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Compatibilidade manifesto × modelo
# ═══════════════════════════════════════════════════════════════════════════════

def check_manifest_compat(db_path: str) -> None:
    _step(f"8. Compatibilidade Manifesto x Modelo  ->  {db_path}")
    try:
        from indexing import validate_embedding_compat
        validate_embedding_compat(db_path)
        _ok("Dimensao e modelo compativeis com o manifesto persistido")
    except RuntimeError as exc:
        _err(str(exc))
    except Exception as exc:
        _err(f"Erro inesperado: {exc}")
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="Debug do pipeline de embedding RAG")
    parser.add_argument("--pdf", default=None, help="Nome do PDF de amostra")
    parser.add_argument("--fix-manifest", action="store_true", help="Remove manifesto corrompido")
    parser.add_argument("--verbose", "-v", action="store_true", help="Detalhes extras")
    args = parser.parse_args()

    print("\n" + "=" * 62)
    print("  RAG Debug -- Pipeline de Embedding")
    print(f"  Base: {_BASE}")
    print("=" * 62)

    from index_manifest import resolve_data_dir, resolve_db_dir
    data_dir = resolve_data_dir(str(_BASE))
    db_path  = resolve_db_dir(str(_BASE))
    print(f"  data_dir : {data_dir}")
    print(f"  db_path  : {db_path}")

    if args.fix_manifest:
        mp = Path(db_path) / "indexed_manifest.json"
        if mp.exists():
            mp.unlink()
            print(f"  Manifesto removido: {mp}")
            print("  Proximo boot vai forcar full rebuild.")
        else:
            print(f"  Manifesto nao existe: {mp}")
        return

    # Carrega .env local (execucao sem Docker)
    _dotenv = _BASE.parent.parent / ".env"
    if _dotenv.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(_dotenv, override=False)
            _info(f".env carregado de {_dotenv}")
        except ImportError:
            _warn("python-dotenv nao instalado; vars de ambiente nao carregadas do .env")

    results: dict[str, bool] = {}

    check_env();                           results["env"]       = True
    results["imports"] = check_imports()
    embed_model, dim   = check_embedding_model()
    results["embedding"] = embed_model is not None
    check_chromadb(db_path, embed_model, dim); results["chromadb"] = True
    check_manifest(db_path, data_dir);         results["manifest"] = True
    check_bm25_cache(db_path);                 results["bm25"]     = True
    check_ingest_sample(data_dir, args.pdf, verbose=args.verbose)
    results["ingest"] = True
    if embed_model is not None:
        check_manifest_compat(db_path)

    print("\n" + "=" * 62)
    print("  SUMARIO")
    print("=" * 62)
    all_ok = True
    for key, ok in results.items():
        status = _OK if ok else _ERR
        print(f"  {status}{key}")
        if not ok:
            all_ok = False
    if all_ok:
        print("\n  Tudo OK. Para mais detalhes, use --verbose")
    else:
        print("\n  Ha problemas. Corrija os itens ERRO acima.")
    print("=" * 62 + "\n")


if __name__ == "__main__":
    main()
