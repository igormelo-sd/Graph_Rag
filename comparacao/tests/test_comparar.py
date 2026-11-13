import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "comparacao" / "avaliacao"))
import comparar  # noqa: E402


def test_sign_test_is_exact_and_ignores_ties():
    assert comparar.sign_test(0, 0) == 1.0
    assert comparar.sign_test(5, 0) == 0.0625          # 2 * (1/32)
    assert comparar.sign_test(3, 3) == 1.0
    assert comparar.sign_test(8, 2) == comparar.sign_test(2, 8)


def test_bootstrap_interval_is_reproducible_and_brackets_the_total():
    differences = [1, 0, 1, 1, 0, -1, 1, 0, 1, 1]
    first, second = comparar.bootstrap_interval(differences), comparar.bootstrap_interval(differences)
    assert first == second and first[0] <= sum(differences) <= first[1]
    assert comparar.bootstrap_interval([]) == (0.0, 0.0)


def write(directory, variant, qid, sources, retrieval=1.0, tokens=100, graph=None):
    diagnostics = {"retrieval_seconds": retrieval, "context_estimated_tokens": tokens}
    if graph is not None:
        diagnostics["graph"] = {"accepted": graph}
    (directory / f"{qid}_{variant}.json").write_text(json.dumps(
        {"sources": sources, "diagnostics": diagnostics}), encoding="utf-8")


def test_report_pairs_versions_by_question_and_averages_rounds(tmp_path, monkeypatch):
    questions = [{"id": f"Q{i}", "categoria": "factual", "fontes": [{"tipo": "pdf", "arquivo": "a.pdf", "pagina_pdf": 1}]}
                 for i in range(1, 5)]
    monkeypatch.setattr(comparar, "load_questions", lambda split: questions)
    hit = [{"source": "a.pdf", "page": 1, "text": "x", "metadata": {"page": 1}}]
    miss = [{"source": "b.pdf", "page": 1, "text": "x", "metadata": {"page": 1}}]
    for run in ("r1", "r2"):
        directory = tmp_path / run
        directory.mkdir()
        for qid in ("Q1", "Q2", "Q3"):
            write(directory, "graph_rag", qid, hit, retrieval=3.0, graph=[{"origin": "label"}])
            write(directory, "simple_rag", qid, hit if qid == "Q1" else miss, retrieval=1.0)
        write(directory, "graph_rag", "Q4", miss, graph=[])
        write(directory, "simple_rag", "Q4", miss)
    result = comparar.report(["r1", "r2"], "teste", ["graph_rag", "simple_rag"], results=tmp_path)
    assert result["resumo"]["graph_rag"]["referencias_no_contexto"] == 3.0
    assert result["resumo"]["simple_rag"]["referencias_no_contexto"] == 1.0
    assert result["resumo"]["graph_rag"]["extras_aceitos_media"] == 0.75
    pair = result["pares"][0]
    assert pair["diferenca_total"] == 2.0 and pair["perguntas_a_favor"] == 2 and pair["perguntas_contra"] == 0
    assert pair["empates"] == 2 and set(pair["perguntas_que_diferem"]) == {"Q2", "Q3"}
    assert pair["por_categoria"]["factual"]["referencias"] == 4
