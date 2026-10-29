"""Atalho para a aplicação GraphRAG em graphrag/main.py."""
from pathlib import Path
import runpy


if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parent / "graphrag" / "main.py"), run_name="__main__")
