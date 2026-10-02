"""
Entry point do RAG Estatístico SP.

Modos de uso:
    python main.py              # inicia servidor FastAPI em :8000
    python main.py --port 9000  # porta customizada
    python main.py --cli        # loop interativo (sem servidor HTTP)
"""
import sys
import os
import argparse
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")

_RAG_ROOT = Path(__file__).resolve().parent
for _p in (str(_RAG_ROOT), str(_RAG_ROOT / "src"), str(_RAG_ROOT / ".agents"),
           str(_RAG_ROOT.parent.parent), str(_RAG_ROOT.parent.parent / ".agents")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _run_server(host: str, port: int) -> None:
    import uvicorn
    from logger import setup_logging
    setup_logging()
    print(f"Iniciando servidor em http://{host}:{port}")
    print(f"Documentacao interativa: http://127.0.0.1:{port}/docs\n")
    uvicorn.run("src.api:app", host=host, port=port, reload=False)


def _run_cli(_use_graph: bool = False) -> None:
    import asyncio
    from dotenv import load_dotenv
    from src.startup import initialize
    from src.query_interpreter import interpret_query
    from src.numerical_validator import validate_numbers, format_validation_report

    load_dotenv()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    engine, interp_llm = initialize(base_dir, use_graph=_use_graph)

    print("=" * 52)
    print(" RAG PRONTO — modo CLI interativo")
    print(" Digite 'sair' para encerrar.")
    print("=" * 52 + "\n")

    while True:
        try:
            pergunta = input("Pergunta: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nEncerrando.")
            break

        if not pergunta:
            continue
        if pergunta.lower() in {"sair", "exit", "quit", "q"}:
            print("Encerrando.")
            break

        try:
            interp = interpret_query(pergunta, interp_llm)
            print(f"  Fontes: {interp['sources']}")
            print(f"  Query reescrita: {interp['rewritten_query']}\n")
            print("Buscando e analisando...\n")

            resposta, source_nodes = asyncio.run(
                engine.answer(
                    question=pergunta,
                    sources=interp["sources"],
                    rewritten_query=interp["rewritten_query"],
                    is_labor_market=interp.get("is_labor_market", False),
                )
            )

            print(f"Resposta:\n{resposta}\n")

            print("Validação numérica:")
            checks = validate_numbers(resposta, source_nodes)
            print(format_validation_report(checks))

            print("\nReferências:")
            for i, node in enumerate(source_nodes):
                fname = node.metadata.get("source_file") or node.metadata.get("file_name", "?")
                score = round((node.score or 0) / 10.0, 2)
                print(f"  [{i+1}] {fname} (relevância: {score:.2f})")

        except Exception as exc:
            print(f"\n[ERRO] {exc}\n")

        print("\n" + "-" * 40 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG Estatístico SP")
    parser.add_argument("--cli",   action="store_true", help="Loop interativo (sem servidor HTTP)")
    parser.add_argument("--graph", action="store_true", help="Habilita GraphRetriever como 4ª fonte")
    parser.add_argument("--host",  default="0.0.0.0",   help="Host do servidor (padrão: 0.0.0.0)")
    parser.add_argument("--port",  type=int, default=8000, help="Porta do servidor (padrão: 8000)")
    args = parser.parse_args()

    if args.cli:
        _run_cli(_use_graph=args.graph)
    else:
        if args.graph:
            os.environ["RAG_USE_GRAPH"] = "1"
        _run_server(args.host, args.port)


if __name__ == "__main__":
    main()
