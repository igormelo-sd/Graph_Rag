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
MODES = ("hybrid", "structural", "llm_graph", "hybrid_no_ontology", "structural_no_ontology", "llm_graph_no_ontology")


def load_cases(path, allow_unscored):
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not cases or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Casos vazios ou IDs duplicados")
    for case in cases:
        if not case.get("question"):
            raise ValueError("Pergunta ausente")
        dimensions = case.get("expected_dimensions", {})
        if not isinstance(dimensions, dict) or any(not isinstance(values, list) or not values or any(not isinstance(value, str) for value in values) for values in dimensions.values()):
            raise ValueError("expected_dimensions exige listas não vazias de identificadores")
        if "expected_clarification" in case and type(case["expected_clarification"]) is not bool:
            raise ValueError("expected_clarification deve ser booleano")
        if not allow_unscored and (not case.get("gold_reviewed") or (not case.get("expected_sources") and case.get("expected_clarification") is not True) or not case.get("expected_answer_contains")):
            raise ValueError("Prepare e revise o gabarito antes de avaliar, ou use --allow-unscored")
    return cases


async def worker(args, cases):
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    # Sobrescreve flags do .env para manter a ablação controlada.
    base_mode = args.mode.removesuffix("_no_ontology")
    ontology_active = not args.mode.endswith("_no_ontology")
    os.environ.update({"RAG_ONTOLOGY_ENABLE": str(int(ontology_active)),
                       "RAG_USE_GRAPH": str(int(base_mode == "llm_graph")),
                       "RAG_GRAPH_STRUCT": str(int(base_mode != "hybrid")),
                       "RAG_GRAPH_EMBED": "0", "RAG_ONTOLOGY_DISCOVER": "0",
                       "RAG_DEEP_SEARCH": "0", "RAG_HYDE": "0",
                       "RAG_INDEX_AUTO_DOWNLOAD": "0", "RAG_INDEX_READ_ONLY": "1",
                       "RAG_GRAPH_DIR": str(args.output / "cache" / args.mode)})
    from startup import initialize
    from query_service import execute_engine_query
    from query_usage import usage_scope
    started = time.perf_counter()
    with usage_scope() as startup_usage:
        engine, llm = initialize(str(ROOT), use_graph=base_mode == "llm_graph")
    startup_seconds = time.perf_counter() - started
    # Mesmas fontes base e reescritas; interpretação não é variável experimental.
    def fixed_interpreter(question, _llm):
        sources = ["text", "tables", "timeseries"]
        if base_mode != "hybrid":
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
                                   "ontology_candidate_count": response.ontology.get("candidate_count"),
                                   "divergence_candidate_count": len(response.knowledge.get("divergences", [])),
                                   "clarification_requested": bool(response.clarification),
                                   "clarification_match": bool(response.clarification) == case["expected_clarification"] if reviewed and "expected_clarification" in case else None,
                                   "retrieval_path_count": len(response.ontology.get("retrieval_paths", [])),
                                   "competency_match": all(
                                       set(values).issubset(set(response.ontology.get("query", {}).get("dimensions", {}).get(key, [])))
                                       for key, values in case.get("expected_dimensions", {}).items()
                                   ) if reviewed and case.get("expected_dimensions") else None,
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
    from domain_ontology import fingerprint, SCHEMA_VERSION
    manifest = {"ontology_hash": fingerprint(), "ontology_version": SCHEMA_VERSION,
                "cases_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
                "requirements_sha256": hashlib.sha256((ROOT / "requirements.txt").read_bytes()).hexdigest(),
                "python": sys.version, "repeats": args.repeats, "modes": MODES,
                "notes": "Correspondência de fragmentos é proxy, não acurácia semântica; custo exclui construção do grafo. _no_ontology desativa anotação, observações, prompts e filtros; contratos de extração e evidência permanecem. competency_match mede reconhecimento de dimensões da pergunta, não qualidade da resposta."}
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
        for metric in ("latency_seconds", "source_recall", "answer_fragment_match", "cost_usd", "ontology_candidate_count", "competency_match", "divergence_candidate_count", "clarification_requested", "clarification_match", "retrieval_path_count"):
            values = [record[metric] for record in records if not record.get("error") and record.get(metric) is not None]
            summary[metric + "_mean"] = statistics.mean(values) if values else None
            summary[metric + "_samples"] = len(values)
        summaries.append(summary)
    (args.output / "summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
