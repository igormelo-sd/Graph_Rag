"""Comparação pareada entre versões numa ou mais rodadas do `avaliar`, sem chamadas de modelos.

Medida principal: referências do gabarito presentes no contexto que cada versão enviou ao modelo
(a mesma de `cobertura.py`, lida direto dos resultados gravados). Como a recuperação é determinística
para um índice fixo, repetir rodadas só varia a geração; por isso as rodadas são agregadas por pergunta
(média das rodadas) antes da comparação.

Para cada par de versões: diferença total de referências, intervalo de confiança por bootstrap sobre as
perguntas (semente fixa), teste dos sinais exato por pergunta (empates descartados) e a lista das perguntas
em que a diferença é não nula. Também resume tempo de recuperação, contexto e extras aceitos.

Uso:
    python comparacao/avaliacao/comparar.py RODADA [RODADA ...] --split teste --versoes simple_rag,graph_rag
"""
import argparse
import json
import math
import random
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from cobertura import covered  # noqa: E402
from resultados import result_file  # noqa: E402

RESULTS = HERE.parent / "artefatos" / "resultados"


def load_questions(split):
    path = HERE / f"{split}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def measure(rounds, split, variants, results=RESULTS):
    """Por versão e pergunta: referências no contexto (média das rodadas), total de referências e métricas."""
    questions = load_questions(split)
    table = {variant: {} for variant in variants}
    extras = {variant: {"retrieval": [], "tokens": [], "accepted": []} for variant in variants}
    for variant in variants:
        for question in questions:
            counts = []
            for run in rounds:
                data = json.loads(result_file(Path(results) / run, question["id"], variant).read_text(encoding="utf-8"))
                counts.append(sum(covered(question["fontes"], data["sources"])))
                extras[variant]["retrieval"].append(data["diagnostics"]["retrieval_seconds"])
                extras[variant]["tokens"].append(data["diagnostics"]["context_estimated_tokens"])
                diagnostics = data["diagnostics"].get("graph") or data["diagnostics"].get("lexical") or {}
                if "accepted" in diagnostics:
                    extras[variant]["accepted"].append(len(diagnostics["accepted"]))
            table[variant][question["id"]] = (statistics.mean(counts), len(question["fontes"]), question["categoria"])
    return questions, table, extras


def sign_test(wins, losses):
    """Valor p bilateral exato do teste dos sinais (empates já descartados)."""
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    probability = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * probability)


def bootstrap_interval(differences, resamples=10000, seed=20261113):
    rng = random.Random(seed)
    n = len(differences)
    if n == 0:
        return (0.0, 0.0)
    totals = sorted(sum(rng.choice(differences) for _ in range(n)) for _ in range(resamples))
    return totals[int(0.025 * resamples)], totals[int(0.975 * resamples) - 1]


def compare_pair(table, first, second):
    ids = sorted(table[first])
    differences = [table[first][i][0] - table[second][i][0] for i in ids]
    wins = sum(d > 0 for d in differences)
    losses = sum(d < 0 for d in differences)
    low, high = bootstrap_interval(differences)
    by_category = {}
    for i in ids:
        mean, total, category = table[first][i]
        entry = by_category.setdefault(category, [0.0, 0.0, 0])
        entry[0] += mean - table[second][i][0]
        entry[1] += total
        entry[2] += 1
    return {"primeira": first, "segunda": second, "diferenca_total": round(sum(differences), 3),
            "intervalo_95": [round(low, 3), round(high, 3)], "perguntas_a_favor": wins, "perguntas_contra": losses,
            "empates": len(ids) - wins - losses, "p_sinais": round(sign_test(wins, losses), 4),
            "por_categoria": {c: {"diferenca": round(v[0], 3), "referencias": int(v[1]), "perguntas": v[2]}
                              for c, v in sorted(by_category.items())},
            "perguntas_que_diferem": {i: [round(table[first][i][0], 2), round(table[second][i][0], 2)]
                                      for i, d in zip(ids, differences) if abs(d) > 1e-9}}


def report(rounds, split, variants, results=RESULTS):
    questions, table, extras = measure(rounds, split, variants, results)
    total = sum(len(q["fontes"]) for q in questions)
    summary = {}
    for variant in variants:
        covered_total = sum(mean for mean, _, _ in table[variant].values())
        e = extras[variant]
        summary[variant] = {"referencias_no_contexto": round(covered_total, 2), "referencias": total,
                            "recuperacao_mediana_s": round(statistics.median(e["retrieval"]), 1),
                            "contexto_mediano_tokens": int(statistics.median(e["tokens"])),
                            "extras_aceitos_media": round(statistics.mean(e["accepted"]), 2) if e["accepted"] else None}
    pairs = [compare_pair(table, a, b) for i, a in enumerate(variants) for b in variants[i + 1:]]
    return {"rodadas": rounds, "split": split, "perguntas": len(questions), "resumo": summary, "pares": pairs}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("rodadas", nargs="+", help="Pastas em artefatos/resultados.")
    parser.add_argument("--split", default="desenvolvimento", choices=("desenvolvimento", "teste"))
    parser.add_argument("--versoes", default="simple_rag,graph_rag")
    parser.add_argument("--json", type=Path, help="Grava o relatório completo neste arquivo.")
    args = parser.parse_args(argv)
    variants = [item.strip() for item in args.versoes.split(",") if item.strip()]
    result = report(args.rodadas, args.split, variants)
    for variant, item in result["resumo"].items():
        extra = f", extras aceitos {item['extras_aceitos_media']}" if item["extras_aceitos_media"] is not None else ""
        print(f"{variant:12s} {item['referencias_no_contexto']}/{item['referencias']} referências no contexto | "
              f"recuperação {item['recuperacao_mediana_s']} s | contexto {item['contexto_mediano_tokens']} tokens{extra}")
    for pair in result["pares"]:
        print(f"\n{pair['primeira']} - {pair['segunda']}: {pair['diferenca_total']:+} referências "
              f"(IC95% {pair['intervalo_95'][0]:+} a {pair['intervalo_95'][1]:+}); perguntas a favor {pair['perguntas_a_favor']}, "
              f"contra {pair['perguntas_contra']}, empates {pair['empates']}; p (sinais) = {pair['p_sinais']}")
        for category, item in pair["por_categoria"].items():
            print(f"    {category:11s} {item['diferenca']:+} de {item['referencias']} referências ({item['perguntas']} perguntas)")
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
