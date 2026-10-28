"""Conta marcadores literais dos gabaritos nas respostas de rodadas do `avaliar`.

Cada marcador é uma expressão regular que aproxima um ponto obrigatório verificável
no texto (um número, um termo). É uma triagem automática para comparar rodadas e
versões; não substitui a rubrica nem a revisão humana. Sem chamadas de modelos.

Uso:
    python comparacao/avaliacao/marcadores.py RODADA [RODADA ...] [--json saida.json]

RODADA é o nome de uma pasta em comparacao/artefatos/resultados/.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "artefatos" / "resultados"
VARIANTS = ("rag_simples", "graphrag")
# Versão do conjunto de desenvolvimento a que os marcadores correspondem.
QUESTIONS_SHA256 = "4147b379a3251ce91861cd6579ebd6024fa58d91740cb7341c6922f91121986d"

MARKERS = {
    "D001": [r"icms"],
    "D002": [r"consumidores residenciais de energia", r"domic[ií]lios"],
    "D003": [r"terceiro trimestre"],
    "D004": [r"lubrificantes"],
    "D005": [r"drs campinas"],
    "D006": [r"-8,3"],
    "D007": [r"2,3 ?%"],
    "D008": [r"31,1"],
    "D009": [r"3\.277,8"],
    "D010": [r"1,59", r"preliminar"],
    "D011": [r"3500105", r"1\.070\.909\.946"],
    "D012": [r"n[aã]o (foram|foi) (iguais|igual)|diferente", r"-0,4", r"-1,2"],
    "D013": [r"uso humano e veterin[aá]rio", r"ortop[eé]dicos"],
    "D014": [r"consumo intermedi[aá]rio|insumos intermedi[aá]rios", r"impostos", r"dupla"],
    "D015": [r"x-13", r"denton|benchmarking"],
    "D016": [r"se[cç][aã]o.*divis[aã]o.*grupo.*classe", r"regi[aã]o administrativa|regi[oõ]es administrativas", r"ibge"],
    "D017": [r"infla[cç][aã]o|pre[cç]os", r"aditiv"],
    "D018": [r"n[aã]o h[aá] informa|n[aã]o (est[aá]|est[aã]o) dispon|n[aã]o fornece"],
    "D019": [r"especificar|n[aã]o especifica|amb[ií]gu|depende d"],
    "D020": [r"\bn[aã]o\b", r"10,3", r"2,3 ?%"],
}
# Afirmação falsa que anula a pergunta: a série municipal não vai até 2026.
FORBIDDEN = {"D018": r"at[eé] 2026"}


def score(question_id, answer):
    text = answer.lower()
    if question_id in FORBIDDEN and re.search(FORBIDDEN[question_id], text):
        return 0
    return sum(bool(re.search(marker, text, re.S)) for marker in MARKERS[question_id])


def summarize(runs):
    questions_path = HERE / "desenvolvimento.jsonl"
    if hashlib.sha256(questions_path.read_bytes()).hexdigest() != QUESTIONS_SHA256:
        raise SystemExit("desenvolvimento.jsonl mudou: revise os marcadores antes de comparar.")
    ids = [json.loads(line)["id"] for line in questions_path.read_text(encoding="utf-8").splitlines()]
    total = sum(len(MARKERS[qid]) for qid in ids)
    rows, summary = [], {}
    for variant in VARIANTS:
        per_run = [0] * len(runs)
        same_ids = same_text = 0
        for qid in ids:
            results = [json.loads((RESULTS / run / f"{qid}_{variant}.json").read_text(encoding="utf-8")) for run in runs]
            scores = [score(qid, result["answer"]) for result in results]
            for index, value in enumerate(scores):
                per_run[index] += value
            stable_ids = len({tuple(r["diagnostics"]["initial_ids"]) for r in results}) == 1
            same_ids += stable_ids
            same_text += len({r["answer"].strip() for r in results}) == 1
            rows.append({"id": qid, "versao": variant, "marcadores": len(MARKERS[qid]),
                         "por_rodada": scores, "trechos_iniciais_iguais": stable_ids})
        summary[variant] = {"por_rodada": per_run, "total_marcadores": total,
                            "media": round(sum(per_run) / len(runs), 2),
                            "perguntas_com_trechos_iguais": same_ids, "respostas_identicas": same_text}
    return {"rodadas": runs, "questions_sha256": QUESTIONS_SHA256, "resumo": summary, "perguntas": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("rodadas", nargs="+")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    report = summarize(args.rodadas)
    for row in report["perguntas"]:
        flag = "  <-- varia" if len(set(row["por_rodada"])) > 1 else ""
        print(f"{row['id']}  {row['versao']:11}  {row['por_rodada']} de {row['marcadores']}{flag}")
    for variant, item in report["resumo"].items():
        print(f"{variant}: {item['por_rodada']} de {item['total_marcadores']} (média {item['media']}); "
              f"trechos iniciais iguais em {item['perguntas_com_trechos_iguais']}/20; "
              f"respostas idênticas em {item['respostas_identicas']}/20")
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
