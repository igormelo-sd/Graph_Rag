"""Executa cada suíte em processo isolado para evitar colisões entre variantes."""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITES = {
    "shared": ROOT / "tests_shared",
    "principal": ROOT / "tests",
    "graphrag": ROOT / "graphrag" / "tests",
    "simples": ROOT / "rag_simples" / "tests",
    "comparacao": ROOT / "comparacao" / "tests",
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", action="append", choices=SUITES)
    args = parser.parse_args(argv)
    failed = []
    for name in args.suite or SUITES:
        print(f"\nExecutando suíte: {name}", flush=True)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(SUITES[name]), "-q"], cwd=ROOT,
            check=False,
        )
        if result.returncode:
            failed.append(name)
    if failed:
        print("Suítes com falhas: " + ", ".join(failed))
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
