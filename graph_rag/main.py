"""Entrada compatível para o RAG Estatístico SP."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag_app.cli import main as run


def main(argv=None):
    run(Path(__file__).resolve().parent, argv, extended=True)


if __name__ == "__main__":
    main()
