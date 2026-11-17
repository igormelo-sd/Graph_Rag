"""Gera a pasta publicável: perguntas, respostas (CSV e Markdown), arquivos usados no embedding e manifesto de hashes.

Sem chamadas de modelos. Lê `artefatos/resultados` (ignorado pelo Git) e o índice local.

Uso:
    python comparacao/avaliacao/publicar_resultados.py
"""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AV = ROOT / "comparacao" / "avaliacao"
OUT = ROOT / "comparacao" / "resultados_publicados"
RESULTS = ROOT / "comparacao" / "artefatos" / "resultados"
ROUNDS = {"r1": ("simple_rag", "lexical_rag", "graph_rag"), "r2": ("simple_rag", "graph_rag"),
          "r3": ("simple_rag", "graph_rag")}
PREFIX = "v4b_teste_20261113_"


def sha(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sources_text(sources):
    return "; ".join(f"[{i}] {s.get('source')} p.{s.get('page')}" for i, s in enumerate(sources, 1))


def main():
    OUT.mkdir(exist_ok=True)
    questions = [json.loads(line) for line in (AV / "teste.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    (OUT / "perguntas_teste.jsonl").write_text(
        "\n".join(json.dumps(q, ensure_ascii=False) for q in questions) + "\n", encoding="utf-8")

    rows = []
    for round_name, variants in ROUNDS.items():
        for q in questions:
            for variant in variants:
                data = json.loads((RESULTS / (PREFIX + round_name) / f"{q['id']}_{variant}.json").read_text(encoding="utf-8"))
                rows.append({"id": q["id"], "categoria": q["categoria"], "pergunta": q["pergunta"], "rodada": round_name,
                             "versao": variant, "resposta": data["answer"], "fontes": sources_text(data["sources"]),
                             "segundos": data.get("total_seconds", "")})
    with open(OUT / "respostas.csv", "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    lines = ["# Perguntas e respostas do teste congelado", "",
             "Todas as respostas (3 rodadas; lexical_rag só na r1). Gabarito conforme `perguntas_teste.jsonl`.", ""]
    for q in questions:
        lines += [f"## {q['id']} ({q['categoria']})", "", f"**Pergunta:** {q['pergunta']}", "",
                  f"**Resposta esperada:** {q['resposta_esperada']}", ""]
        for row in (r for r in rows if r["id"] == q["id"]):
            lines += [f"### {row['rodada']} · {row['versao']}", "", row["resposta"].strip(), "",
                      f"_Fontes: {row['fontes']}_", ""]
    (OUT / "respostas_legiveis.md").write_text("\n".join(lines), encoding="utf-8")

    corpus = json.loads((AV / "manifesto_corpus.json").read_text(encoding="utf-8"))["arquivos"]
    index = json.loads((ROOT / "simple_rag" / "indice" / "index.json").read_text(encoding="utf-8"))
    counts = Counter(chunk["source"] for chunk in index["chunks"])
    index_manifest = json.loads((ROOT / "simple_rag" / "indice" / "manifesto.json").read_text(encoding="utf-8"))
    known = {item["arquivo"] for item in corpus}
    with open(OUT / "arquivos_embedding.csv", "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["arquivo", "tipo", "bytes", "sha256", "sha256_confere_com_data", "entrou_no_embedding", "trechos", "tabela_truncada_em_1000_linhas"])
        for item in corpus:
            path = ROOT / "data" / item["arquivo"]
            matches = path.is_file() and sha(path) == item["sha256"]
            writer.writerow([item["arquivo"], item["tipo"], item["bytes"], item["sha256"], "sim" if matches else "NAO",
                             "sim" if counts.get(item["arquivo"]) else "nao", counts.get(item["arquivo"], 0),
                             "sim" if item["tipo"] in ("csv", "xlsx") and counts.get(item["arquivo"]) == 1000 else "nao"])
    extra = sorted(set(counts) - known)

    files = sorted(p for p in OUT.rglob("*") if p.is_file() and p.name != "MANIFESTO.json")
    manifest = {"gerado_de": "comparacao/avaliacao/publicar_resultados.py", "congelamento":
                "comparacao/avaliacao/congelamento_20261113_gpt54mini.json", "indice": index_manifest,
                "trechos_total": len(index["chunks"]), "fontes_no_indice_fora_do_manifesto_do_corpus": extra,
                "arquivos": {str(p.relative_to(OUT)).replace("\\", "/"): sha(p) for p in files}}
    (OUT / "MANIFESTO.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(rows)} respostas; {len(corpus)} arquivos no corpus; {len(counts)} fontes no índice; fora do manifesto: {extra}")


if __name__ == "__main__":
    main()
