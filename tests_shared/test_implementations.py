"""rag_simples e graphrag: mesmo código, com o grafo só no graphrag."""
import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SIMPLE, GRAPH = ROOT / "rag_simples" / "src", ROOT / "graphrag" / "src"

# Módulos que só existem no GraphRAG.
GRAPH_ONLY = {"graph_indexing", "graph_retriever", "graph_ontology", "ontology_extractor",
              "relation_semantics", "community_search", "entity_resolution"}
# Módulos com a mesma função nas duas pastas, mas sem os ganchos de grafo no simples.
GRAPH_AWARE = {"analysis_engine", "startup", "query_interpreter", "parent_context", "domain_ontology"}


def modules(folder):
    return {path.stem for path in folder.glob("*.py")}


def test_simple_has_no_graph_module_and_graphrag_has_them_all():
    assert not (modules(SIMPLE) & GRAPH_ONLY)
    assert GRAPH_ONLY - {"entity_resolution"} <= modules(GRAPH)


def test_simple_is_graphrag_minus_graph_only_modules():
    assert modules(SIMPLE) == modules(GRAPH) - GRAPH_ONLY


@pytest.mark.parametrize("name", sorted(modules(SIMPLE) - GRAPH_AWARE) if SIMPLE.is_dir() else [])
def test_shared_modules_are_byte_identical(name):
    assert (SIMPLE / f"{name}.py").read_bytes() == (GRAPH / f"{name}.py").read_bytes()


def test_simple_never_imports_graph_modules():
    for path in SIMPLE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            names = ([node.module] if isinstance(node, ast.ImportFrom) and node.module
                     else [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
            assert not {name.split(".")[0] for name in names} & GRAPH_ONLY, path.name


def test_simple_config_matches_graphrag():
    assert ((ROOT / "rag_simples/config/ontology_extensions.json").read_bytes()
            == (ROOT / "graphrag/config/ontology_extensions.json").read_bytes())


def test_graph_flag_is_rejected_by_simple_entry_point(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "rag_simples" / "main.py"), "--cli", "--graph"],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 2
    assert "sem módulos de grafo" in result.stderr
