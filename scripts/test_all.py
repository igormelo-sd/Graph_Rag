"""Executa cada suíte em processo isolado para evitar colisões entre as implementações."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# nome -> (pasta de testes, variáveis de ambiente extras)
SUITES = {
    "shared": (ROOT / "tests_shared", {}),
    "graph_rag": (ROOT / "graph_rag" / "tests", {}),
    # Mesma suíte do graph_rag contra simple_rag/src (testes de grafo são pulados).
    "simple_rag_src": (ROOT / "graph_rag" / "tests", {"RAG_TEST_IMPL": "simple_rag"}),
    "simple_rag": (ROOT / "simple_rag" / "tests", {}),
    "comparacao": (ROOT / "comparacao" / "tests", {}),
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", action="append", choices=SUITES)
    args = parser.parse_args(argv)
    failed = []
    for name in args.suite or SUITES:
        folder, extra = SUITES[name]
        print(f"\nExecutando suíte: {name}", flush=True)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(folder), "-q"], cwd=ROOT,
            env={**os.environ, **extra}, check=False,
        )
        if result.returncode:
            failed.append(name)
    if failed:
        print("Suítes com falhas: " + ", ".join(failed))
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
