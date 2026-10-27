"""Comparação controlada: mesmos nós, vetores, busca inicial e síntese final."""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

# Executado como script, a pasta comparacao/ entraria no caminho de importação e
# comparacao/profile.py esconderia o módulo `profile` da biblioteca padrão (usado
# pelo torch no reranker). Os módulos daqui são importados como `comparacao.*`.
_HERE = Path(__file__).resolve().parent
sys.path[:] = [entry for entry in sys.path if not entry or Path(entry).resolve() != _HERE]
sys.path.insert(0, str(_HERE.parent))
from comparacao.common import ROOT, config, apply_profile, fingerprint, graph_modules, pack_results
from comparacao.variants import REGISTRY

VARIANTS = tuple(REGISTRY)
# v2: linhas de rodapé das planilhas viram notas da tabela (comparacao/footnotes.py).
# v3: fragmentos curtos anexados e tabelas pequenas reunidas (comparacao/chunk_repair.py).
PIPELINE = "shared-graph-processing-v3"

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


def experiment_signature(settings, snapshot=None):
    return {"profile": fingerprint(settings), "corpus": snapshot or corpus_snapshot(settings),
            "pipeline": PIPELINE}


def simple_rag(settings):
    from rag_simples.rag import SimpleRAG
    return SimpleRAG(ARTIFACTS / "index.json", settings["embedding_model"], settings["llm_model"])


def prepare():
    settings = apply_profile(strict=True)
    graph_modules()
    from ingestion import load_documents
    from processing import process_documents
    from rag_simples.rag import Chunk
    started = time.perf_counter()
    snapshot = corpus_snapshot(settings)
    documents = load_documents(str((ROOT / settings["corpus"]).resolve()), save_output=False)
    from comparacao.footnotes import separate_table_footnotes
    from comparacao.chunk_repair import join_short_fragments, merge_small_tables
    nodes, footnotes = separate_table_footnotes(process_documents(documents))
    nodes, fragments = join_short_fragments(nodes, settings["min_text_chars"])
    nodes, small_tables = merge_small_tables(nodes, settings["small_table_rows"], settings["small_table_chars"])
    if not nodes:
        raise ValueError("Nenhum trecho extraído do corpus.")
    if corpus_snapshot(settings) != snapshot:
        raise ValueError("Corpus alterado durante a preparação. Execute preparar novamente.")
    experiment = experiment_signature(settings, snapshot)
    chunks = [Chunk(node.text, str(node.metadata.get("source_file", "?")),
                    node.metadata.get("page"), int(node.metadata.get("chunk_id", 1)),
                    dict(node.metadata)) for node in nodes]
    rag = simple_rag(settings)
    count = rag.index_chunks(chunks, settings["chunk_size"], settings["chunk_overlap"], experiment)
    return {"chunks": count, "footnote_rows_removed": footnotes, "short_fragments_joined": fragments,
            "small_tables_merged": small_tables, "profile": experiment["profile"],
            "corpus_files": len(snapshot),
            "preparation_seconds": round(time.perf_counter() - started, 3), "index": str(rag.index_path)}


def load_experiment_nodes(rag, expected, payload=None):
    """Valida perfil, corpus e IDs antes de carregar qualquer modelo."""
    from llama_index.core.schema import TextNode
    payload = payload or rag.load_index()
    if payload.get("experiment") != expected:
        raise ValueError("Perfil ou corpus mudou. Execute comparacao/run.py preparar novamente.")
    metadata = [item.get("metadata") for item in payload["chunks"]]
    identities = [item.get("node_id") if isinstance(item, dict) else None for item in metadata]
    invalid_ids = any(not isinstance(identity, str) or not identity.strip() for identity in identities)
    if invalid_ids or len(set(identities)) != len(identities):
        raise ValueError("Índice experimental com node_id ausente ou duplicado. Execute preparar novamente.")
    return [TextNode(id_=item["metadata"]["node_id"], text=item["text"], metadata=item["metadata"])
            for item in payload["chunks"]]


class Session:
    """Índice, modelos e estratégias carregados uma vez e reutilizados entre perguntas.

    O grafo do GraphRAG é determinístico para um índice fixo e só é lido nas
    consultas; por isso pode ser montado uma única vez por sessão.
    """

    def __init__(self, settings, variants=VARIANTS):
        graph_modules()
        from comparacao.common import embedding_model, load_openai_key
        from comparacao.retrieval import BM25Index, Reranker
        load_openai_key()
        self.settings = settings
        self.rag = simple_rag(settings)
        self.expected = experiment_signature(settings)
        self.payload = self.rag.load_index()
        self.nodes = load_experiment_nodes(self.rag, self.expected, self.payload)
        self.by_id = {node.node_id: node for node in self.nodes}
        self.bm25 = BM25Index(self.payload["chunks"]) if settings["retrieval_mode"] == "hybrid" else None
        self.reranker = Reranker(settings["reranker"]) if settings["reranker"] else None
        self._initial = {}
        # Modelos carregados antes da cronometragem da recuperação.
        self.rag.client
        self.rag.embedder = embedding_model(settings["embedding_model"])
        # Estratégias (inclusive o grafo) montadas aqui, para o custo ficar na abertura da sessão.
        self._strategies = {variant: REGISTRY[variant](self.nodes, self.rag.client, settings, ARTIFACTS)
                            for variant in variants}

    def initial(self, question):
        """Ranking inicial e seu tempo, calculados uma vez por pergunta e comuns às versões."""
        if question not in self._initial:
            from comparacao.retrieval import initial_ranking
            started = time.perf_counter()
            ranking = initial_ranking(question, self.rag, self.payload, self.settings, self.bm25, self.reranker)
            self._initial[question] = (ranking, time.perf_counter() - started)
        return self._initial[question]

    def strategy(self, variant):
        if variant not in self._strategies:
            raise ValueError(f"Versão não carregada nesta sessão: {variant}.")
        return self._strategies[variant]


def compare(question, variant, session=None):
    if not isinstance(question, str) or not question.strip() or variant not in VARIANTS:
        raise ValueError("Informe uma pergunta e escolha rag_simples ou graphrag.")
    if session is None:
        session = Session(apply_profile(strict=True), (variant,))
    from llama_index.core.schema import NodeWithScore
    settings, rag, expected = session.settings, session.rag, session.expected
    strategy = session.strategy(variant)

    # O ranking inicial é o mesmo para as duas versões; seu tempo entra em ambas.
    initial, initial_seconds = session.initial(question)
    started = time.perf_counter()
    ranked = [NodeWithScore(node=session.by_id[item["metadata"]["node_id"]], score=item["score"])
              for item in initial]
    retrieval = strategy.retrieve(question, ranked)
    context, used = pack_results(retrieval.results, settings["context_tokens"])
    diagnostics = {"mode": variant, "initial_ids": [item.node_id for item in ranked],
                   "initial_ranks": [item["ranks"] for item in initial],
                   "initial_ranking_seconds": round(initial_seconds, 3),
                   "profile": expected["profile"], "corpus": expected["corpus"],
                   "graph_extraction": strategy.graph_extraction, **retrieval.diagnostics,
                   "retrieval_seconds": round(initial_seconds + time.perf_counter() - started, 3),
                   "context_estimated_tokens": (len(context) + 3) // 4}

    generation_started = time.perf_counter()
    answer = rag.answer(question, used)
    diagnostics["generation_seconds"] = round(time.perf_counter() - generation_started, 3)
    diagnostics["settings"] = settings
    return {"answer": answer, "sources": used, "diagnostics": diagnostics}


QUESTIONS = Path(__file__).with_name("avaliacao")
SPLITS = ("desenvolvimento", "teste")


def _completed(path):
    try:
        return "erro" not in json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False


def evaluate(split, output, ids=None):
    """Roda um conjunto de perguntas nas duas versões, numa só sessão, com retomada.

    Envia somente `pergunta`. A ordem das versões alterna por pergunta. Execuções
    já gravadas sem erro são mantidas; as demais são refeitas. Retomar com outro
    perfil, corpus ou banco de perguntas é recusado.
    """
    from rag_app.storage import write_json
    if split not in SPLITS:
        raise ValueError("Conjunto inválido: use desenvolvimento ou teste.")
    if not output or Path(output).name != output or output in {".", ".."}:
        raise ValueError("Informe em --saida apenas o nome de uma pasta de resultados.")
    source = QUESTIONS / f"{split}.jsonl"
    raw = source.read_bytes()
    questions = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if ids:
        missing = set(ids) - {question["id"] for question in questions}
        if missing:
            raise ValueError(f"IDs inexistentes em {split}: {', '.join(sorted(missing))}.")
        questions = [question for question in questions if question["id"] in ids]
    settings = apply_profile(strict=True)
    directory = ARTIFACTS / "resultados" / output
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifesto.json"
    identity = {"split": split, "questions_sha256": hashlib.sha256(raw).hexdigest(),
                **experiment_signature(settings)}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {
        **identity, "settings": settings, "sent_fields": ["pergunta"],
        "variants_order": "alternada por pergunta", "runs": []}
    if any(manifest.get(key) != value for key, value in identity.items()):
        raise ValueError("A pasta já contém resultados de outro perfil, corpus ou banco de perguntas.")
    if any(directory.glob("*_*.json")) and not manifest_path.exists():
        raise ValueError("A pasta tem resultados sem manifesto; use outra pasta em --saida.")
    # Gravado antes das execuções: uma interrupção não deixa resultados sem identidade.
    write_json(manifest_path, manifest)

    run_log = {"started": time.strftime("%Y-%m-%dT%H:%M:%S"), "executed": [], "kept": [], "errors": []}
    session, session_seconds = None, None
    for position, question in enumerate(questions):
        order = VARIANTS if position % 2 == 0 else VARIANTS[::-1]
        for variant in order:
            label = f"{question['id']}_{variant}"
            target = directory / f"{label}.json"
            if _completed(target):
                run_log["kept"].append(label)
                continue
            if session is None:
                opened = time.perf_counter()
                session = Session(settings)
                session_seconds = round(time.perf_counter() - opened, 3)
            started = time.perf_counter()
            record = {"id": question["id"], "pergunta": question["pergunta"], "versao": variant}
            try:
                record.update(compare(question["pergunta"], variant, session))
            except Exception as exc:  # registra e segue; a retomada refaz a execução
                record["erro"] = f"{type(exc).__name__}: {exc}"
                run_log["errors"].append(label)
            record["total_seconds"] = round(time.perf_counter() - started, 3)
            write_json(target, record)
            run_log["executed"].append(label)
            print(label, "erro" if "erro" in record else "ok", record["total_seconds"], file=sys.stderr, flush=True)
    changed = session is not None and experiment_signature(settings) != session.expected
    run_log.update(finished=time.strftime("%Y-%m-%dT%H:%M:%S"), session_seconds=session_seconds,
                   corpus_changed=changed)
    manifest["runs"].append(run_log)
    write_json(manifest_path, manifest)
    if changed:
        raise ValueError("Corpus alterado durante a avaliação. Os resultados desta execução não são válidos.")
    return {"saida": str(directory), "executadas": len(run_log["executed"]),
            "mantidas": len(run_log["kept"]), "erros": run_log["errors"], "sessao_segundos": session_seconds}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("preparar")
    query = subcommands.add_parser("perguntar")
    query.add_argument("pergunta")
    query.add_argument("--versao", choices=VARIANTS, required=True)
    batch = subcommands.add_parser("avaliar", help="Roda um conjunto de perguntas nas duas versões.")
    batch.add_argument("--split", choices=SPLITS, required=True)
    batch.add_argument("--saida", required=True, help="Pasta em artefatos/resultados; reutilize para retomar.")
    batch.add_argument("--ids", help="IDs separados por vírgula, por exemplo D001,D002.")
    args = parser.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name(".env"), override=True)
    from comparacao.common import load_openai_key
    load_openai_key()
    try:
        if args.command == "preparar":
            result = prepare()
        elif args.command == "avaliar":
            ids = [item.strip() for item in args.ids.split(",") if item.strip()] if args.ids else None
            result = evaluate(args.split, args.saida, ids)
        else:
            result = compare(args.pergunta, args.versao)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Erro: {exc}\n")


if __name__ == "__main__":
    main()
