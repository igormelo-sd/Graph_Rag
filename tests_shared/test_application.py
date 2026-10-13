import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from comparacao.profile import load_profile
from rag_app.bootstrap import activate
from rag_app.cli import main
from rag_app.storage import write_json

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("entry", ["main.py", "graphrag/main.py"])
def test_help_from_another_directory_without_site_packages(entry, tmp_path):
    result = subprocess.run([sys.executable, "-S", str(ROOT / entry), "--help"],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "--index-only" in result.stdout


@pytest.mark.parametrize("argv", [
    ["--cli", "--index-only"], ["--graph", "--index-only"],
    ["--comparacao-completa"], ["--comparar", " "],
    ["--prepare-communities", "--cli"], ["--comparar", "teste", "--graph"],
])
def test_invalid_modes_fail_before_initialization(argv):
    with pytest.raises(SystemExit) as error:
        main(ROOT / "graphrag", argv, extended=True)
    assert error.value.code == 2


def test_bootstrap_rejects_already_loaded_other_variant(monkeypatch):
    monkeypatch.setitem(sys.modules, "processing", SimpleNamespace(__file__=str(ROOT / "src/processing.py")))
    with pytest.raises(RuntimeError, match="processo separado"):
        activate(ROOT / "graphrag")


def test_bootstrap_prioritizes_selected_implementation(monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))
    activate(ROOT / "graphrag")
    assert sys.path[0] == str(ROOT / "graphrag/src")


@pytest.mark.parametrize("key,value", [
    ("chunk_overlap", True), ("entity_context_depth", 0.5),
    ("temperature", float("nan")), ("llm_model", " "), ("top_k", None),
])
def test_invalid_profile_fields_report_the_field(tmp_path, key, value):
    settings = json.loads((ROOT / "comparacao/config.json").read_text())
    settings[key] = value
    path = tmp_path / "config.json"
    path.write_text(json.dumps(settings), encoding="utf-8")
    with pytest.raises(ValueError, match=key):
        load_profile(path)


def test_failed_serialization_preserves_index_and_cleans_temporary(tmp_path):
    path = tmp_path / "index.json"
    write_json(path, {"previous": True})
    before = path.read_bytes()
    with pytest.raises(ValueError):
        write_json(path, {"invalid": float("nan")})
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


def test_index_replacement(tmp_path):
    path = tmp_path / "index.json"
    write_json(path, {"version": 1})
    write_json(path, {"version": 2})
    assert json.loads(path.read_text()) == {"version": 2}


def test_page_metadata_preserves_grouping_order_and_explicit_sections():
    from rag_app.provenance import assign_page_metadata
    nodes = [SimpleNamespace(metadata={"source_file": file, "page": page})
             for file, page in [("a", 1), ("b", 1), ("a", 1), ("a", 2)]]
    nodes[2].metadata["section"] = "Título próprio"
    documents = [SimpleNamespace(metadata={"source_file": "a", "page": 1, "section": "Economia"})]
    assign_page_metadata(nodes, documents)
    assert [node.metadata["chunk_id"] for node in nodes] == [1, 1, 2, 1]
    assert [node.metadata["total_chunks_page"] for node in nodes] == [2, 1, 2, 1]
    assert nodes[0].metadata["section"] == "Economia"
    assert nodes[2].metadata["section"] == "Título próprio"
    assert "section" not in nodes[1].metadata


def test_graph_entry_dispatches_only_graphrag(monkeypatch, capsys):
    from unittest.mock import Mock
    from rag_app import cli
    from comparacao import run
    compare = Mock(return_value={"answer": "ok"})
    monkeypatch.setattr(cli, "activate", lambda _: None)
    monkeypatch.setattr(cli, "configure_console", lambda: None)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)
    monkeypatch.setattr(run, "compare", compare)
    cli.main(ROOT / "graphrag", ["--comparar", "Pergunta"], extended=True)
    compare.assert_called_once_with("Pergunta", "graphrag")
    assert json.loads(capsys.readouterr().out)["answer"] == "ok"


def test_comparison_help_exposes_exactly_two_implementations():
    from comparacao import run
    assert run.VARIANTS == ("rag_simples", "graphrag")
    result = subprocess.run([sys.executable, "-S", str(ROOT / "comparacao/run.py"),
                             "perguntar", "--help"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "{rag_simples,graphrag}" in result.stdout
    assert "grafo_completo" not in result.stdout
