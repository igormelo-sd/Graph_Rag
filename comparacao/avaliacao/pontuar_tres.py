"""Pontua uma ficha preenchida com três rótulos (A/B/C), revelando as versões pela chave.

`cega.py pontuar` só aceita dois sistemas. Esta ferramenta lê o formato do pacote de avaliação com três rótulos
(`ficha_preenchida_*.json` + `_chave/chave.json`) e calcula, por versão: médias por componente da rubrica e do total
(0 a 8, pesos iguais), por categoria, e a comparação pareada por pergunta (bootstrap do IC95% da diferença média do total
e teste dos sinais exato). Sem chamadas de modelos. Não declara o avaliador: o registro da ficha (`avaliador`, `natureza`)
é copiado para o relatório.

Uso:
    python comparacao/avaliacao/pontuar_tres.py FICHA.json CHAVE.json --json saida.json
"""
import argparse
import json
import random
from math import comb
from pathlib import Path

AV = Path(__file__).resolve().parent
COMPONENTS = ("correcao", "apoio_documental", "completude", "qualificacao")
PAIRS = (("graph_rag", "simple_rag"), ("lexical_rag", "simple_rag"), ("graph_rag", "lexical_rag"))


def sign_test(wins, losses):
    n = wins + losses
    if n == 0:
        return 1.0
    tail = sum(comb(n, k) for k in range(max(wins, losses), n + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def bootstrap_ci(diffs, seed=20261117, draws=10000):
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(rng.choice(diffs) for _ in range(n)) / n for _ in range(draws))
    return means[int(0.025 * draws)], means[int(0.975 * draws) - 1]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("ficha")
    parser.add_argument("chave")
    parser.add_argument("--json")
    args = parser.parse_args()
    sheet = json.loads(Path(args.ficha).read_text(encoding="utf-8"))
    key = json.loads(Path(args.chave).read_text(encoding="utf-8"))
    if sheet["ficha_id"] != key["ficha_id"]:
        raise SystemExit("A chave não corresponde a esta ficha (ficha_id diferente).")
    category = {}
    for line in (AV / "teste.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            category[row["id"]] = row["categoria"]

    scores = {}  # versão -> pergunta -> {componente: nota, total, recuperacao}
    for qid, question in sheet["perguntas"].items():
        for label, answer in question["respostas"].items():
            version = key["chave"][qid][label]
            notes = {name: answer["componentes"][name]["nota"] for name in COMPONENTS}
            notes["total"] = sum(notes.values())
            notes["recuperacao"] = answer.get("recuperacao")
            scores.setdefault(version, {})[qid] = notes
    versions = sorted(scores)
    ids = sorted(next(iter(scores.values())))
    if any(sorted(scores[v]) != ids for v in versions):
        raise SystemExit("Versões com conjuntos de perguntas diferentes.")

    def mean(values):
        values = list(values)
        return sum(values) / len(values) if values else 0.0

    report = {"ficha_id": sheet["ficha_id"], "rodada": sheet["rodada"], "avaliador": sheet.get("avaliador"),
              "natureza": sheet.get("natureza"), "perguntas": len(ids), "versoes": {}, "comparacoes": {}}
    for version in versions:
        entry = {name: round(mean(scores[version][q][name] for q in ids), 3) for name in COMPONENTS + ("total",)}
        entry["recuperacao_sim"] = sum(1 for q in ids if scores[version][q]["recuperacao"] == "sim")
        entry["por_categoria"] = {}
        for cat in sorted(set(category[q] for q in ids)):
            cat_ids = [q for q in ids if category[q] == cat]
            entry["por_categoria"][cat] = {"perguntas": len(cat_ids),
                                           "total": round(mean(scores[version][q]["total"] for q in cat_ids), 3)}
        report["versoes"][version] = entry
    for first, second in PAIRS:
        if first not in scores or second not in scores:
            continue
        diffs = [scores[first][q]["total"] - scores[second][q]["total"] for q in ids]
        wins, losses = sum(d > 0 for d in diffs), sum(d < 0 for d in diffs)
        low, high = bootstrap_ci(diffs)
        by_category = {}
        for cat in sorted(set(category[q] for q in ids)):
            by_category[cat] = round(mean(d for q, d in zip(ids, diffs) if category[q] == cat), 3)
        report["comparacoes"][f"{first} - {second}"] = {
            "diferenca_media_total": round(mean(diffs), 3), "ic95": [round(low, 3), round(high, 3)],
            "a_favor": wins, "contra": losses, "empates": len(diffs) - wins - losses,
            "p_sinais": round(sign_test(wins, losses), 4), "por_categoria": by_category,
            "perguntas_com_diferenca": {q: d for q, d in zip(ids, diffs) if d}}

    print(f"Ficha {sheet['ficha_id']} | {sheet.get('avaliador')} | {len(ids)} perguntas")
    for version, entry in report["versoes"].items():
        parts = " ".join(f"{name[:5]} {entry[name]:.2f}" for name in COMPONENTS)
        print(f"{version:12s} total {entry['total']:.2f}/8 | {parts} | recuperação 'sim' {entry['recuperacao_sim']}/{len(ids)}")
    for name, comp in report["comparacoes"].items():
        print(f"{name}: {comp['diferenca_media_total']:+.2f} (IC95% {comp['ic95'][0]:+.2f} a {comp['ic95'][1]:+.2f}); "
              f"a favor {comp['a_favor']}, contra {comp['contra']}, empates {comp['empates']}; p = {comp['p_sinais']}")
        print("    por categoria:", comp["por_categoria"])
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
