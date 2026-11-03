"""Cobertura das referências do gabarito no contexto de cada versão, sem chamadas de API.

Reaproveita os trechos iniciais gravados numa rodada (`<id>_rag_simples.json`),
o índice experimental local, o grafo e o reranker local. Para cada pergunta,
conta quantas referências do gabarito aparecem no contexto que cada versão
enviaria ao modelo e quantas já estavam nos trechos iniciais. Com
`--candidatos`, conta as referências presentes entre os candidatos do grafo,
antes do reranker. É uma triagem da recuperação: não avalia respostas, e uma
referência no contexto não garante que a resposta a use.

Uma referência PDF é encontrada pelo arquivo e pela página; XLSX, pela aba, pelo
valor literal e pelo rótulo da linha; CSV, pelos valores do registro.
"""
import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))


def matches(reference, item):
    metadata = item.get("metadata") or {}
    if item["source"] != reference["arquivo"]:
        return False
    if reference["tipo"] == "pdf":
        return str(metadata.get("page")) == str(reference["pagina_pdf"])
    text = item["text"]
    if reference["tipo"] == "xlsx":
        return (str(metadata.get("page")) == reference["aba"] and reference["valor_literal"] in text
                and reference["rotulo_linha"] in text)
    return all(str(value) in text for value in reference["campos"].values() if str(value).strip())


def covered(references, items):
    return [any(matches(reference, item) for item in items) for reference in references]


def load_session(variants):
    from comparacao.common import apply_profile, graph_modules
    settings = apply_profile(strict=True)
    graph_modules()
    from comparacao.run import ARTIFACTS, experiment_signature, load_experiment_nodes, simple_rag
    from comparacao.variants import REGISTRY
    rag = simple_rag(settings)
    nodes = load_experiment_nodes(rag, experiment_signature(settings))
    reranker = None
    if settings["reranker"] and any(getattr(REGISTRY[v], "uses_reranker", False) for v in variants):
        from comparacao.retrieval import Reranker
        reranker = Reranker(settings["reranker"])
    strategies = {}
    for variant in variants:
        extra = {"reranker": reranker} if getattr(REGISTRY[variant], "uses_reranker", False) else {}
        strategies[variant] = REGISTRY[variant](nodes, None, settings, ARTIFACTS, **extra)
    return settings, {node.node_id: node for node in nodes}, strategies, ARTIFACTS


def measure(round_name, variants, split="desenvolvimento", candidates=False):
    from llama_index.core.schema import NodeWithScore
    from comparacao.common import pack_results
    from comparacao.variants import as_result
    settings, by_id, strategies, artifacts = load_session(variants)
    directory = artifacts / "resultados" / round_name
    questions = [json.loads(line) for line in (HERE / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()
                 if line.strip()]
    report = {"rodada": round_name, "split": split, "versoes": {}}
    for variant, strategy in strategies.items():
        rows = []
        for question in questions:
            initial = json.loads((directory / f"{question['id']}_rag_simples.json").read_text(encoding="utf-8"))["sources"]
            ranked = [NodeWithScore(node=by_id[item["metadata"]["node_id"]], score=item["score"]) for item in initial]
            references = question["fontes"]
            row = {"id": question["id"], "referencias": len(references), "iniciais": sum(covered(references, initial))}
            started = time.perf_counter()
            if candidates:
                proposed = strategy.candidates(question["pergunta"], ranked) if hasattr(strategy, "candidates") else []
                found = [as_result(item) for item in proposed]
                row["candidatos"] = sum(covered(references, found))
            else:
                retrieval = strategy.retrieve(question["pergunta"], ranked)
                context, used = pack_results(retrieval.results, settings["context_tokens"])
                row.update(contexto=sum(covered(references, used)), tokens=(len(context) + 3) // 4,
                           aceitos=[item["origin"] for item in retrieval.diagnostics.get("graph", {}).get("accepted", [])])
            row["segundos"] = round(time.perf_counter() - started, 2)
            rows.append(row)
        key = "candidatos" if candidates else "contexto"
        report["versoes"][variant] = {
            "referencias": sum(row["referencias"] for row in rows), "iniciais": sum(row["iniciais"] for row in rows),
            key: sum(row[key] for row in rows), "perguntas": rows}
        if not candidates:
            report["versoes"][variant]["tokens_medios"] = round(sum(row["tokens"] for row in rows) / len(rows))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("rodada", help="Pasta em artefatos/resultados com <id>_rag_simples.json de cada pergunta.")
    parser.add_argument("--versoes", default="rag_pais,graphrag")
    parser.add_argument("--split", default="desenvolvimento", choices=("desenvolvimento", "teste"))
    parser.add_argument("--candidatos", action="store_true", help="Conta referências entre os candidatos do grafo.")
    args = parser.parse_args(argv)
    variants = [item.strip() for item in args.versoes.split(",") if item.strip()]
    report = measure(args.rodada, variants, args.split, args.candidatos)
    for variant, summary in report["versoes"].items():
        found = summary.get("contexto", summary.get("candidatos"))
        extra = f", tokens médios {summary['tokens_medios']}" if "tokens_medios" in summary else ""
        print(f"{variant}: {found}/{summary['referencias']} referências (iniciais {summary['iniciais']}){extra}")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
