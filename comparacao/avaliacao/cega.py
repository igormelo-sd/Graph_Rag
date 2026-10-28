"""Avaliação humana cega das respostas pela rubrica, com revisão dos gabaritos.

gerar    Monta uma ficha HTML para uma rodada do `avaliar`: em cada pergunta, o
         gabarito a revisar e as duas respostas como A e B, em ordem sorteada, com
         as fontes que cada resposta cita. A chave A/B fica em `_chave/`.
pontuar  Valida a ficha preenchida (exportada pelo HTML), revela as versões e
         calcula as médias por componente da rubrica, por categoria e por pergunta.

A revisão dos gabaritos fica na ficha, não em `desenvolvimento.jsonl`, para não
alterar o conjunto congelado. Sem chamadas de modelos.

Uso:
    python comparacao/avaliacao/cega.py gerar --rodada openai_rerank_dev_20261028_r1 --saida cega_r1
    python comparacao/avaliacao/cega.py pontuar --saida cega_r1 --preenchida ficha_preenchida.json
"""
import argparse
import hashlib
import html
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARTIFACTS = HERE.parent / "artefatos"
RESULTS = ARTIFACTS / "resultados"
OUTPUT = ARTIFACTS / "avaliacao_cega"
VARIANTS = ("rag_simples", "graphrag")
DIMENSIONS = ("correcao", "apoio_documental", "completude", "qualificacao")
GABARITO = ("aprovado", "corrigido", "rejeitado")
RECUPERACAO = ("sim", "parcial", "nao")
CITATION = re.compile(r"\[(\d+)\]")


def cited_sources(result):
    """Fontes citadas pela resposta, na numeração do contexto que ela recebeu.

    Mostrar só as citadas evita que o número de fontes revele a versão; o apoio
    documental é julgado sobre o que a resposta efetivamente cita.
    """
    numbers = sorted({int(n) for n in CITATION.findall(result["answer"])})
    sources = result["sources"]
    return [{"numero": n, "arquivo": sources[n - 1]["source"], "pagina": str(sources[n - 1]["page"]),
             "texto": sources[n - 1]["text"]} for n in numbers if 1 <= n <= len(sources)]


def locator(source):
    if source["tipo"] == "pdf":
        return f"página PDF {source['pagina_pdf']}"
    if source["tipo"] == "csv":
        return f"linha {source['linha']}"
    return f"{source['aba']}!{source['celula']}"


def build(run, seed):
    questions = [json.loads(line) for line in (HERE / "desenvolvimento.jsonl").read_text(encoding="utf-8").splitlines()]
    rng = random.Random(seed)
    items, key = [], {}
    for question in questions:
        results = {v: json.loads((RESULTS / run / f"{question['id']}_{v}.json").read_text(encoding="utf-8"))
                   for v in VARIANTS}
        if any("erro" in result for result in results.values()):
            raise SystemExit(f"{question['id']} tem execução com erro na rodada {run}.")
        order = list(VARIANTS)
        rng.shuffle(order)
        key[question["id"]] = {"A": order[0], "B": order[1]}
        items.append({
            "id": question["id"], "categoria": question["categoria"], "pergunta": question["pergunta"],
            "comportamento_esperado": question["comportamento_esperado"],
            "resposta_esperada": question["resposta_esperada"], "pontos": question["pontos_obrigatorios"],
            "fontes_gabarito": [{"arquivo": s["arquivo"], "local": locator(s), "trecho": s.get("trecho", "")}
                                for s in question["fontes"]],
            "limitacao": (question.get("limitacao_indexacao") or {}).get("descricao", ""),
            "respostas": {label: {"texto": results[variant]["answer"], "fontes": cited_sources(results[variant])}
                          for label, variant in (("A", order[0]), ("B", order[1]))},
        })
    data = {"rodada": run, "itens": items}
    data["ficha_id"] = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    return data, {"ficha_id": data["ficha_id"], "rodada": run, "semente": seed, "chave": key}


PAGE = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Avaliação cega</title>
<style>
:root{--bg:#fafaf8;--card:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#ddd9d0;--accent:#2f5d8a;--warn:#9a5b00;--ok:#2e7d4f}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#1f1f1d;--ink:#ecebe6;--muted:#a4a39c;--line:#3a3934;--accent:#7fb0e0;--warn:#e0a650;--ok:#7cc79a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,Segoe UI,sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center}
header input{padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--ink)}
button{padding:6px 12px;border:1px solid var(--accent);background:var(--accent);color:#fff;border-radius:6px;cursor:pointer}
button.sec{background:transparent;color:var(--accent)}
main{max-width:1100px;margin:0 auto;padding:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:20px}
.card.done{border-left:4px solid var(--ok)}
h2{margin:0 0 4px;font-size:17px}.meta{color:var(--muted);font-size:13px}
.gab{border:1px dashed var(--line);border-radius:8px;padding:10px;margin:10px 0}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:800px){.cols{grid-template-columns:1fr}}
.ans{border:1px solid var(--line);border-radius:8px;padding:10px}
.ans h3{margin:0 0 6px;font-size:15px}.txt{white-space:pre-wrap;background:var(--bg);padding:8px;border-radius:6px;max-height:340px;overflow:auto}
details{margin:6px 0}summary{cursor:pointer;color:var(--accent)}pre{white-space:pre-wrap;font-size:12px;max-height:220px;overflow:auto;background:var(--bg);padding:6px;border-radius:6px}
table{width:100%;border-collapse:collapse;margin-top:8px}td{padding:4px;vertical-align:top;border-top:1px solid var(--line)}
textarea,select,input[type=text]{width:100%;padding:4px 6px;border:1px solid var(--line);border-radius:5px;background:var(--card);color:var(--ink);font:inherit}
textarea{min-height:34px}.lim{color:var(--warn);font-size:13px}label{margin-right:10px}
</style></head><body>
<header><strong>Avaliação cega</strong><span class="meta">ficha __FICHA__</span>
<input id="avaliador" placeholder="Avaliador(a)"><span id="prog" class="meta"></span>
<button id="exp">Exportar JSON</button><button id="imp" class="sec">Importar JSON</button><input id="file" type="file" accept=".json" hidden>
</header><main id="main"></main>
<script>
const DATA = __DATA__;
const DIMS = [["correcao","Correção"],["apoio_documental","Apoio documental"],["completude","Completude"],["qualificacao","Qualificação"]];
const KEY = "avaliacao-cega-" + DATA.ficha_id;
let state = {}; try { state = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { state = {}; }
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} progress(); };
function radios(path, options) { return options.map(o => `<label><input type="radio" name="${path}" value="${o}" data-k="${path}"> ${o}</label>`).join(""); }
function answer(item, label) {
  const a = item.respostas[label], base = item.id + ".respostas." + label;
  const fontes = a.fontes.length ? a.fontes.map(f => `<details><summary>[${f.numero}] ${esc(f.arquivo)} — ${esc(f.pagina)}</summary><pre>${esc(f.texto)}</pre></details>`).join("") : '<p class="meta">A resposta não cita fontes numeradas.</p>';
  const pontos = item.pontos.map((p, i) => `<tr><td>${esc(p)}</td><td style="width:120px">${radios(base + ".pontos." + i + ".atendido", ["sim","nao"])}</td><td><input type="text" data-k="${base}.pontos.${i}.evidencia" placeholder="evidência na resposta"></td></tr>`).join("");
  const dims = DIMS.map(([k, n]) => `<tr><td>${n}</td><td style="width:90px"><select data-k="${base}.componentes.${k}.nota"><option value=""></option><option>0</option><option>1</option><option>2</option></select></td><td><textarea data-k="${base}.componentes.${k}.justificativa" placeholder="justificativa"></textarea></td></tr>`).join("");
  return `<div class="ans"><h3>Resposta ${label}</h3><div class="txt">${esc(a.texto)}</div><div class="meta">Fontes citadas</div>${fontes}
  <table><tr><td colspan="3"><strong>Pontos obrigatórios</strong></td></tr>${pontos}</table>
  <table><tr><td colspan="3"><strong>Rubrica (0–2)</strong></td></tr>${dims}</table>
  <p>Evidências necessárias recuperadas? ${radios(base + ".recuperacao", ["sim","parcial","nao"])}</p></div>`;
}
function render() {
  document.getElementById("main").innerHTML = DATA.itens.map(item => `<section class="card" id="c-${item.id}">
  <h2>${item.id} — ${esc(item.pergunta)}</h2><div class="meta">${item.categoria} · comportamento esperado: ${item.comportamento_esperado}</div>
  ${item.limitacao ? `<p class="lim">${esc(item.limitacao)}</p>` : ""}
  <div class="gab"><strong>Gabarito:</strong> ${esc(item.resposta_esperada)}<ul>${item.pontos.map(p => `<li>${esc(p)}</li>`).join("")}</ul>
  ${item.fontes_gabarito.map(f => `<details><summary>${esc(f.arquivo)} — ${esc(f.local)}</summary><pre>${esc(f.trecho)}</pre></details>`).join("")}
  <p>Revisão do gabarito: ${radios(item.id + ".gabarito.status", ["aprovado","corrigido","rejeitado"])}</p>
  <textarea data-k="${item.id}.gabarito.observacao" placeholder="correção ou motivo (obrigatório se corrigido ou rejeitado)"></textarea></div>
  <div class="cols">${answer(item, "A")}${answer(item, "B")}</div></section>`).join("");
  document.querySelectorAll("[data-k]").forEach(el => {
    const k = el.dataset.k, v = state[k];
    if (el.type === "radio") { el.checked = v === el.value; el.addEventListener("change", () => { state[k] = el.value; save(); }); }
    else { if (v !== undefined) el.value = v; el.addEventListener("input", () => { state[k] = el.value; save(); }); }
  });
  const av = document.getElementById("avaliador"); av.value = state.avaliador || "";
  av.addEventListener("input", () => { state.avaliador = av.value; save(); });
  progress();
}
function complete(item) {
  const g = state[item.id + ".gabarito.status"]; if (!g) return false; if (g === "rejeitado") return true;
  return ["A","B"].every(l => { const b = item.id + ".respostas." + l;
    return state[b + ".recuperacao"] && item.pontos.every((p, i) => state[b + ".pontos." + i + ".atendido"] && (state[b + ".pontos." + i + ".evidencia"] || "").trim())
      && DIMS.every(([k]) => state[b + ".componentes." + k + ".nota"] && (state[b + ".componentes." + k + ".justificativa"] || "").trim()); });
}
function progress() {
  let n = 0; DATA.itens.forEach(it => { const ok = complete(it); n += ok; const c = document.getElementById("c-" + it.id); if (c) c.classList.toggle("done", ok); });
  document.getElementById("prog").textContent = `${n}/${DATA.itens.length} perguntas completas`;
}
function exportJSON() {
  const out = {ficha_id: DATA.ficha_id, avaliador: state.avaliador || "", perguntas: {}};
  DATA.itens.forEach(item => {
    const q = {gabarito: {status: state[item.id + ".gabarito.status"] || null, observacao: state[item.id + ".gabarito.observacao"] || ""}, respostas: {}};
    ["A","B"].forEach(l => { const b = item.id + ".respostas." + l;
      q.respostas[l] = {recuperacao: state[b + ".recuperacao"] || null,
        pontos: item.pontos.map((p, i) => ({atendido: state[b + ".pontos." + i + ".atendido"] ? state[b + ".pontos." + i + ".atendido"] === "sim" : null, evidencia: state[b + ".pontos." + i + ".evidencia"] || ""})),
        componentes: Object.fromEntries(DIMS.map(([k]) => [k, {nota: state[b + ".componentes." + k + ".nota"] ? Number(state[b + ".componentes." + k + ".nota"]) : null, justificativa: state[b + ".componentes." + k + ".justificativa"] || ""}]))}; });
    out.perguntas[item.id] = q; });
  const blob = new Blob([JSON.stringify(out, null, 2)], {type: "application/json"});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "ficha_preenchida_" + DATA.ficha_id + ".json"; a.click();
}
function importJSON(file) {
  file.text().then(t => { const d = JSON.parse(t); if (d.ficha_id !== DATA.ficha_id) { alert("Arquivo de outra ficha."); return; }
    state = {avaliador: d.avaliador};
    Object.entries(d.perguntas).forEach(([id, q]) => { state[id + ".gabarito.status"] = q.gabarito.status; state[id + ".gabarito.observacao"] = q.gabarito.observacao;
      Object.entries(q.respostas).forEach(([l, r]) => { const b = id + ".respostas." + l; state[b + ".recuperacao"] = r.recuperacao;
        r.pontos.forEach((p, i) => { if (p.atendido !== null) state[b + ".pontos." + i + ".atendido"] = p.atendido ? "sim" : "nao"; state[b + ".pontos." + i + ".evidencia"] = p.evidencia; });
        Object.entries(r.componentes).forEach(([k, c]) => { if (c.nota !== null) state[b + ".componentes." + k + ".nota"] = String(c.nota); state[b + ".componentes." + k + ".justificativa"] = c.justificativa; }); }); });
    save(); render(); });
}
document.getElementById("exp").onclick = exportJSON;
document.getElementById("imp").onclick = () => document.getElementById("file").click();
document.getElementById("file").onchange = e => e.target.files[0] && importJSON(e.target.files[0]);
render();
</script></body></html>
"""


def generate(args):
    directory = OUTPUT / args.saida
    if directory.exists():
        raise SystemExit(f"{directory} já existe; use outro nome em --saida.")
    seed = args.semente if args.semente is not None else random.SystemRandom().randrange(2**31)
    data, key = build(args.rodada, seed)
    (directory / "_chave").mkdir(parents=True)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    (directory / "ficha.html").write_text(PAGE.replace("__DATA__", payload).replace("__FICHA__", html.escape(data["ficha_id"])),
                                          encoding="utf-8")
    (directory / "_chave" / "chave.json").write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ficha": str(directory / "ficha.html"), "ficha_id": data["ficha_id"],
                      "chave": str(directory / "_chave" / "chave.json")}, ensure_ascii=False, indent=2))


def validate(filled, data):
    problems = []
    if filled.get("ficha_id") != data["ficha_id"]:
        problems.append("ficha_id diferente da ficha gerada.")
    if not str(filled.get("avaliador", "")).strip():
        problems.append("Avaliador(a) não identificado(a).")
    for item in data["itens"]:
        qid, row = item["id"], filled.get("perguntas", {}).get(item["id"])
        if row is None:
            problems.append(f"{qid}: ausente.")
            continue
        status = row["gabarito"]["status"]
        if status not in GABARITO:
            problems.append(f"{qid}: revisão do gabarito sem decisão.")
            continue
        if status != "aprovado" and not row["gabarito"]["observacao"].strip():
            problems.append(f"{qid}: gabarito {status} sem observação.")
        if status == "rejeitado":
            continue
        for label in ("A", "B"):
            answer = row["respostas"][label]
            if answer["recuperacao"] not in RECUPERACAO:
                problems.append(f"{qid} {label}: recuperação não marcada.")
            if len(answer["pontos"]) != len(item["pontos"]):
                problems.append(f"{qid} {label}: número de pontos diferente do gabarito.")
            for index, point in enumerate(answer["pontos"], 1):
                if type(point["atendido"]) is not bool or not point["evidencia"].strip():
                    problems.append(f"{qid} {label}: ponto {index} sem decisão ou evidência.")
            for dimension in DIMENSIONS:
                component = answer["componentes"][dimension]
                if component["nota"] not in (0, 1, 2) or type(component["nota"]) is not int or not component["justificativa"].strip():
                    problems.append(f"{qid} {label}: {dimension} sem nota 0–2 ou justificativa.")
    return problems


def summarize(filled, data, key):
    categories = {item["id"]: item["categoria"] for item in data["itens"]}
    per_version = {v: {"perguntas": 0, "componentes": {d: 0 for d in DIMENSIONS}, "pontos_atendidos": 0,
                       "pontos_total": 0, "recuperacao": {r: 0 for r in RECUPERACAO}, "por_categoria": {}}
                   for v in VARIANTS}
    per_question, excluded, gabaritos = [], [], {}
    for qid, row in filled["perguntas"].items():
        gabaritos[qid] = row["gabarito"]
        if row["gabarito"]["status"] == "rejeitado":
            excluded.append(qid)
            continue
        totals = {}
        for label, answer in row["respostas"].items():
            version = key["chave"][qid][label]
            stats = per_version[version]
            stats["perguntas"] += 1
            total = 0
            for dimension in DIMENSIONS:
                stats["componentes"][dimension] += answer["componentes"][dimension]["nota"]
                total += answer["componentes"][dimension]["nota"]
            stats["pontos_atendidos"] += sum(point["atendido"] for point in answer["pontos"])
            stats["pontos_total"] += len(answer["pontos"])
            stats["recuperacao"][answer["recuperacao"]] += 1
            category = stats["por_categoria"].setdefault(categories[qid], {"perguntas": 0, "soma_total": 0})
            category["perguntas"] += 1
            category["soma_total"] += total
            totals[version] = total
        per_question.append({"id": qid, "categoria": categories[qid], "total_0_8": totals,
                             "diferenca_graphrag_menos_simples": totals["graphrag"] - totals["rag_simples"]})
    for stats in per_version.values():
        n = stats["perguntas"] or 1
        stats["medias_por_componente"] = {d: round(stats["componentes"].pop(d) / n, 3) for d in DIMENSIONS}
        stats.pop("componentes")
        stats["media_total_0_8"] = round(sum(stats["medias_por_componente"].values()), 3)
        for category in stats["por_categoria"].values():
            category["media_total_0_8"] = round(category.pop("soma_total") / category["perguntas"], 3)
    differences = [row["diferenca_graphrag_menos_simples"] for row in per_question]
    return {"ficha_id": data["ficha_id"], "rodada": data["rodada"], "avaliador": filled["avaliador"],
            "metodo": "rubrica_humana_cega_por_componente", "perguntas_pontuadas": len(per_question),
            "gabaritos_rejeitados": excluded, "por_versao": per_version,
            "comparacao": {"graphrag_melhor": sum(d > 0 for d in differences),
                           "empates": sum(d == 0 for d in differences),
                           "rag_simples_melhor": sum(d < 0 for d in differences)},
            "por_pergunta": per_question, "revisao_gabaritos": gabaritos}


def score(args):
    directory = OUTPUT / args.saida
    html_text = (directory / "ficha.html").read_text(encoding="utf-8")
    data = json.loads(re.search(r"const DATA = (.*);\nconst DIMS", html_text, re.S)[1].replace("<\\/", "</"))
    key = json.loads((directory / "_chave" / "chave.json").read_text(encoding="utf-8"))
    filled = json.loads(Path(args.preenchida).read_text(encoding="utf-8"))
    problems = validate(filled, data)
    if problems:
        print("Ficha incompleta; nada foi revelado:", *problems, sep="\n- ", file=sys.stderr)
        raise SystemExit(1)
    report = summarize(filled, data, key)
    (directory / "resultado.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("perguntas_pontuadas", "gabaritos_rejeitados", "comparacao")}
                     | {"medias": {v: report["por_versao"][v]["medias_por_componente"] | {"total_0_8": report["por_versao"][v]["media_total_0_8"]}
                                   for v in VARIANTS}}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="comando", required=True)
    make = sub.add_parser("gerar")
    make.add_argument("--rodada", required=True, help="Pasta em artefatos/resultados.")
    make.add_argument("--saida", required=True, help="Pasta nova em artefatos/avaliacao_cega.")
    make.add_argument("--semente", type=int, help="Sorteio A/B reproduzível; omitida, é aleatória e registrada na chave.")
    grade = sub.add_parser("pontuar")
    grade.add_argument("--saida", required=True)
    grade.add_argument("--preenchida", required=True, help="JSON exportado pela ficha.")
    args = parser.parse_args()
    generate(args) if args.comando == "gerar" else score(args)


if __name__ == "__main__":
    main()
