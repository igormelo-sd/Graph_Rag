"""Comparação controlada: mesmos nós, vetores, busca inicial e síntese final."""
import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comparacao.common import ROOT, config, apply_profile, fingerprint, graph_modules, llm_model, pack_results

VARIANTS = ("rag_simples", "graphrag")

ARTIFACTS = Path(__file__).with_name("artefatos")


def corpus_snapshot(settings):
    directory = (ROOT / settings["corpus"]).resolve()
    if not directory.is_dir():
        raise ValueError(f"Corpus não encontrado: {directory}")
    files = []
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".pdf", ".csv", ".xlsx", ".xls", ".txt"}:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            files.append({"file": path.relative_to(directory).as_posix(), "sha256": digest.hexdigest()})
    if not files:
        raise ValueError("O corpus não contém documentos suportados.")
    return files


def prepare():
    settings = apply_profile(strict=True)
    graph_modules()
    from ingestion import load_documents
    from processing import process_documents
    from rag_simples.rag import SimpleRAG, Chunk
    started = time.perf_counter()
    snapshot = corpus_snapshot(settings)
    documents = load_documents(str((ROOT / settings["corpus"]).resolve()), save_output=False)
    nodes = process_documents(documents)
    if not nodes:
        raise ValueError("Nenhum trecho extraído do corpus.")
    if corpus_snapshot(settings) != snapshot:
        raise ValueError("Corpus alterado durante a preparação. Execute preparar novamente.")
    experiment = {"profile": fingerprint(settings), "corpus": snapshot,
                  "pipeline": "shared-graph-processing-v1"}
    chunks = [Chunk(node.text, str(node.metadata.get("source_file", "?")),
                    node.metadata.get("page"), int(node.metadata.get("chunk_id", 1)),
                    dict(node.metadata)) for node in nodes]
    rag = SimpleRAG(ARTIFACTS / "index.json", settings["embedding_model"], settings["llm_model"])
    count = rag.index_chunks(chunks, settings["chunk_size"], settings["chunk_overlap"], experiment)
    return {"chunks": count, "profile": experiment["profile"], "corpus_files": len(snapshot),
            "preparation_seconds": round(time.perf_counter() - started, 3), "index": str(rag.index_path)}


def compare(question, variant):
    if not isinstance(question, str) or not question.strip() or variant not in VARIANTS:
        raise ValueError("Informe uma pergunta e escolha rag_simples ou graphrag.")
    settings = apply_profile(strict=True)
    graph_modules()
    from rag_simples.rag import SimpleRAG
    from llama_index.core.schema import TextNode, NodeWithScore
    rag = SimpleRAG(ARTIFACTS / "index.json", settings["embedding_model"], settings["llm_model"])
    payload = rag.load_index()
    expected = {"profile": fingerprint(settings), "corpus": corpus_snapshot(settings),
                "pipeline": "shared-graph-processing-v1"}
    if payload.get("experiment") != expected:
        raise ValueError("Perfil ou corpus mudou. Execute comparacao/run.py preparar novamente.")
    metadata = [item.get("metadata") for item in payload["chunks"]]
    identities = [item.get("node_id") if isinstance(item, dict) else None for item in metadata]
    invalid_ids = any(not isinstance(identity, str) or not identity.strip() for identity in identities)
    if invalid_ids or len(set(identities)) != len(identities):
        raise ValueError("Índice experimental com node_id ausente ou duplicado. Execute preparar novamente.")
    # Modelo e cache carregados antes da cronometragem da recuperação.
    rag.client
    from comparacao.common import embedding_model
    rag._embedder = embedding_model(settings["embedding_model"])
    nodes = [TextNode(id_=item["metadata"]["node_id"], text=item["text"], metadata=item["metadata"])
             for item in payload["chunks"]]
    by_id = {node.node_id: node for node in nodes}
    graph = None
    if variant == "graphrag":
        from llama_index.core.graph_stores import SimplePropertyGraphStore
        from graph_indexing import _inject_structural_triplets, _inject_domain_triplets
        from graph_retriever import GraphRetriever
        from types import SimpleNamespace
        store = SimplePropertyGraphStore()
        _inject_structural_triplets(store, nodes)
        _inject_domain_triplets(store, nodes)
        graph = GraphRetriever(SimpleNamespace(property_graph_store=store), None, use_llm=False)
    started = time.perf_counter()
    initial = rag.search(question, settings["top_k"])
    ranked = [NodeWithScore(node=by_id[item["metadata"]["node_id"]], score=item["score"]) for item in initial]
    diagnostics = {"mode": variant, "initial_ids": [item.node_id for item in ranked],
                   "profile": fingerprint(settings), "corpus": expected["corpus"],
                   "graph_extraction": "registered_entities_only" if graph else "disabled"}
    if graph is not None:
        extra = graph.retrieve_entity_context(ranked, question)
        extra += graph.retrieve_context(ranked, settings["graph_context_limit"])
        seen = {item.node_id for item in ranked}
        for item in extra:
            if item.node_id not in seen:
                seen.add(item.node_id)
                ranked.append(item)
    if graph is not None:
        from community_search import is_global_question, CommunitySearch
    if graph is not None and is_global_question(question):
        search = CommunitySearch(store, nodes, rag.client, ARTIFACTS / "community_summaries.json")
        summaries = search.summaries()
        blocks = [f"[Comunidade {item['id']}]\n{item['summary']}" for item in summaries]
        summary = search._reduce(blocks, "Consolide evidências relevantes à pergunta, preservando fontes. Pergunta: " + question)
        results = [{"text": summary, "source": "resumos de comunidades (derivados)", "page": None,
                    "number": 1, "score": 0.0, "metadata": {"source_ids": sorted(search.nodes)}}]
        diagnostics["all_communities_processed"] = True
        diagnostics["communities"] = len(summaries)
    else:
        if variant == "graphrag":
            from parent_context import expand_parents
            ranked = expand_parents(ranked)
        results = [{"text": item.node.text, "source": item.metadata.get("source_file", "?"),
                    "page": item.metadata.get("page"), "number": item.metadata.get("chunk_id"),
                    "score": item.score, "metadata": dict(item.metadata)} for item in ranked]
    context, used = pack_results(results, settings["context_tokens"])
    diagnostics["retrieval_seconds"] = round(time.perf_counter() - started, 3)
    diagnostics["context_estimated_tokens"] = (len(context) + 3) // 4
    generation_started = time.perf_counter()
    answer = rag.answer(question, used)
    diagnostics["generation_seconds"] = round(time.perf_counter() - generation_started, 3)
    diagnostics["settings"] = settings
    return {"answer": answer, "sources": used, "diagnostics": diagnostics}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("preparar")
    query = subcommands.add_parser("perguntar")
    query.add_argument("pergunta")
    query.add_argument("--versao", choices=VARIANTS, required=True)
    args = parser.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name(".env"), override=True)
    if not os.getenv("OPENAI_API_KEY"):
        # Somente a chave: as demais variáveis RAG_* da raiz não entram no perfil controlado.
        from dotenv import dotenv_values
        key = dotenv_values(ROOT / ".env").get("OPENAI_API_KEY")
        if key:
            os.environ["OPENAI_API_KEY"] = key
    try:
        result = prepare() if args.command == "preparar" else compare(args.pergunta, args.versao)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Erro: {exc}\n")


if __name__ == "__main__":
    main()
