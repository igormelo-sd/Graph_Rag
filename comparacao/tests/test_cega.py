import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from comparacao.avaliacao import cega

QUESTIONS = [json.loads(line) for line in
             (cega.HERE / "desenvolvimento.jsonl").read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def rodada(tmp_path, monkeypatch):
    results, output = tmp_path / "resultados", tmp_path / "avaliacao_cega"
    run = results / "rodada"
    run.mkdir(parents=True)
    for question in QUESTIONS:
        for number, variant in enumerate(cega.VARIANTS):
            sources = [{"source": "fonte.pdf", "page": 1, "text": f"trecho {i}"} for i in range(1, 4)]
            (run / f"{question['id']}_{variant}.json").write_text(json.dumps(
                {"answer": f"Resposta {number} [1][3] [9]", "sources": sources}), encoding="utf-8")
    monkeypatch.setattr(cega, "RESULTS", results)
    monkeypatch.setattr(cega, "OUTPUT", output)
    cega.generate(SimpleNamespace(rodada="rodada", saida="cega", semente=7, split="desenvolvimento"))
    return output / "cega"


def test_sheet_can_use_the_test_split(tmp_path, monkeypatch):
    run = tmp_path / "rodada"
    run.mkdir()
    questions = [json.loads(line) for line in (cega.HERE / "teste.jsonl").read_text(encoding="utf-8").splitlines()]
    for question in questions:
        for variant in cega.VARIANTS:
            (run / f"{question['id']}_{variant}.json").write_text(json.dumps({"answer": "Resposta", "sources": []}), encoding="utf-8")
    monkeypatch.setattr(cega, "RESULTS", tmp_path)
    data, key = cega.build("rodada", 7, "teste")
    assert len(data["itens"]) == 50 and set(key["chave"]) == {question["id"] for question in questions}


def filled(directory, **overrides):
    page = (directory / "ficha.html").read_text(encoding="utf-8")
    data = json.loads(re.search(r"const DATA = (.*);\nconst DIMS", page, re.S)[1].replace("<\\/", "</"))
    key = json.loads((directory / "_chave" / "chave.json").read_text(encoding="utf-8"))
    answers = {}
    for item in data["itens"]:
        respostas = {}
        for label in ("A", "B"):
            nota = 2 if key["chave"][item["id"]][label] == "graph_rag" else 1
            respostas[label] = {"recuperacao": "sim",
                                "pontos": [{"atendido": True, "evidencia": "ok"} for _ in item["pontos"]],
                                "componentes": {d: {"nota": nota, "justificativa": "j"} for d in cega.DIMENSIONS}}
        answers[item["id"]] = {"gabarito": {"status": "aprovado", "observacao": ""}, "respostas": respostas}
    result = {"ficha_id": data["ficha_id"], "avaliador": "Pessoa", "perguntas": answers}
    result.update(overrides)
    path = directory / "preenchida.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    return path, result


def test_sheet_hides_versions_and_shows_only_cited_sources(rodada):
    page = (rodada / "ficha.html").read_text(encoding="utf-8")
    assert "simple_rag" not in page and "graph_rag" not in page
    data = json.loads(re.search(r"const DATA = (.*);\nconst DIMS", page, re.S)[1].replace("<\\/", "</"))
    assert len(data["itens"]) == 20
    assert [f["numero"] for f in data["itens"][0]["respostas"]["A"]["fontes"]] == [1, 3]
    key = json.loads((rodada / "_chave" / "chave.json").read_text(encoding="utf-8"))
    assert key["semente"] == 7 and set(key["chave"]["D001"].values()) == set(cega.VARIANTS)
    assert {key["chave"][q]["A"] for q in key["chave"]} == set(cega.VARIANTS)  # o sorteio alterna


def test_complete_sheet_reveals_versions_and_scores(rodada, capsys):
    path, _ = filled(rodada)
    cega.score(SimpleNamespace(saida="cega", preenchida=str(path)))
    report = json.loads((rodada / "resultado.json").read_text(encoding="utf-8"))
    assert report["por_versao"]["graph_rag"]["media_total_0_8"] == 8
    assert report["por_versao"]["simple_rag"]["media_total_0_8"] == 4
    assert report["comparacao"] == {"graph_rag_melhor": 20, "empates": 0, "simple_rag_melhor": 0}


def test_incomplete_or_rejected_sheets(rodada):
    path, data = filled(rodada)
    data["perguntas"]["D001"]["respostas"]["A"]["componentes"]["correcao"]["justificativa"] = ""
    data["perguntas"]["D002"]["gabarito"] = {"status": "corrigido", "observacao": ""}
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SystemExit):
        cega.score(SimpleNamespace(saida="cega", preenchida=str(path)))
    assert not (rodada / "resultado.json").exists()
    path, data = filled(rodada)
    data["perguntas"]["D003"]["gabarito"] = {"status": "rejeitado", "observacao": "fonte errada"}
    data["perguntas"]["D003"]["respostas"] = {}
    path.write_text(json.dumps(data), encoding="utf-8")
    cega.score(SimpleNamespace(saida="cega", preenchida=str(path)))
    report = json.loads((rodada / "resultado.json").read_text(encoding="utf-8"))
    assert report["gabaritos_rejeitados"] == ["D003"] and report["perguntas_pontuadas"] == 19
