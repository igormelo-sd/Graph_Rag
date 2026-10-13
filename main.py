"""Entrada compatível para o RAG Estatístico SP."""
from pathlib import Path
from rag_app.cli import main as run


def main(argv=None):
    run(Path(__file__).resolve().parent, argv, extended=False)


if __name__ == "__main__":
    main()
