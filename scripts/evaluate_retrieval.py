"""Avaliação opt-in: nunca importada pelo servidor ou pela suíte de testes.

Só execute após autorizar consumo de LLM e preparar o gabarito.
Cada modo roda em um processo separado, com caches de grafo separados.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
MODES = ("hybrid", "structural", "llm_graph")


def load_cases(path, allow_unscored):
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not cases or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Casos vazios ou IDs duplicados")
    for case in cases:
        if not case.get("question"):
            raise ValueError("Pergunta ausente")
        if not allow_unscored and (not case.get("gold_reviewed") or not case.get("expected_sources") or not case.get("expected_answer_contains")):
            raise ValueError("Prepare e revise o gabarito antes de avaliar, ou use --allow-unscored")
    return cases


async def worker(args, cases):
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    # Sobrescreve flags do .env para manter a ablação controlada.
    os.environ.update({"RAG_USE_GRAPH": str(int(args.mode == "llm_graph")),
                       "RAG_GRAPH_STRUCT": str(int(args.mode != "hybrid")),
                       "RAG_GRAPH_EMBED": "0", "RAG_ONTOLOGY_DISCOVER": "0",
                       "RAG_DEEP_SEARCH": "0", "RAG_HYDE": "0",
                       "RAG_INDEX_AUTO_DOWNLOAD": "0", "RAG_INDEX_READ_ONLY": "1",
                       "RAG_GRAPH_DIR": str(args.output / "cache" / args.mode)})
    from startup import initialize
    from query_service import execute_engine_query
    from query_usage import usage_scope
    started = time.perf_counter()
    with usage_scope() as startup_usage:
        engine, llm = initialize(str(ROOT), use_graph=args.mode == "llm_graph")
    startup_seconds = time.perf_counter() - started
    # Mesmas fontes e reescritas nos três modos; interpretação não é variável experimental.
    def fixed_interpreter(question, _llm):
        sources = ["text", "tables", "timeseries"]
        if args.mode == "llm_graph":
            sources.append("graph")
        return {"sources": sources, "rewritten_query": question, "is_labor_market": False}
    target = args.output / f"{args.mode}.jsonl"
    with target.open("w", encoding="utf-8") as stream:
        for repeat in range(args.repeats):
            for case in cases:
                start = time.perf_counter()
                record = {"id": case["id"], "mode": args.mode, "repeat": repeat,
                          "startup_seconds": startup_seconds, "startup_usage": startup_usage.snapshot(),
                          "question": case["question"]}
                try:
                    response, _ = await execute_engine_query(
                        question=case["question"], engine=engine, interp_llm=llm,
                        interpreter=fixed_interpreter, rag_type=args.mode, rag_label=args.mode)
                    actual = {source.file for source in response.sources}
                    expected = set(case.get("expected_sources", []))
                    reviewed = bool(case.get("gold_reviewed"))
                    fragments = case.get("expected_answer_contains", [])
                    record.update({"response": response.model_dump(),
                                   "source_recall": len(actual & expected) / len(expected) if reviewed and expected else None,
                                   "answer_fragment_match": sum(part.casefold() in response.answer.casefold() for part in fragments) / len(fragments) if reviewed and fragments else None,
                                   "cost_usd": response.usage.get("cost_usd"), "error": None})
                except Exception as exc:
                    record["error"] = f"{type(exc).__name__}: {exc}"
                record["latency_seconds"] = time.perf_counter() - start
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--allow-unscored", action="store_true")
    parser.add_argument("--mode", choices=MODES)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats deve ser positivo")
    args.cases, args.output = args.cases.resolve(), args.output.resolve()
    cases = load_cases(args.cases, args.allow_unscored)
    args.output.mkdir(parents=True, exist_ok=True)
    if args.mode:
        asyncio.run(worker(args, cases))
        return
    # Preserve resultados anteriores; o usuário escolhe outro diretório por execução.
    if any((args.output / f"{mode}.jsonl").exists() for mode in MODES):
        parser.error("O diretório já contém resultados; escolha outro --output")
    manifest = {"cases_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
                "requirements_sha256": hashlib.sha256((ROOT / "requirements.txt").read_bytes()).hexdigest(),
                "python": sys.version, "repeats": args.repeats, "modes": MODES,
                "notes": "Correspondência de fragmentos é proxy, não acurácia semântica; custo exclui construção do grafo."}
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    summaries = []
    for mode in MODES:
        command = [sys.executable, str(Path(__file__)), str(args.cases), "--output", str(args.output),
                   "--mode", mode, "--repeats", str(args.repeats)]
        if args.allow_unscored:
            command.append("--allow-unscored")
        subprocess.run(command, check=True, cwd=ROOT)
        records = [json.loads(line) for line in (args.output / f"{mode}.jsonl").read_text(encoding="utf-8").splitlines()]
        summary = {"mode": mode, "errors": sum(bool(r.get("error")) for r in records),
                   "startup_seconds": records[0]["startup_seconds"],
                   "startup_usage": records[0]["startup_usage"]}
        for metric in ("latency_seconds", "source_recall", "answer_fragment_match", "cost_usd"):
            values = [record[metric] for record in records if not record.get("error") and record.get(metric) is not None]
            summary[metric + "_mean"] = statistics.mean(values) if values else None
            summary[metric + "_samples"] = len(values)
        summaries.append(summary)
    (args.output / "summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
