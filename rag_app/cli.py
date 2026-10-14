"""Despacho comum dos comandos das duas implementações GraphRAG."""
import argparse
import json
import os
from pathlib import Path

from rag_app.bootstrap import activate, configure_console


def build_parser(*, extended: bool = False) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RAG Estatístico SP")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--index-only", action="store_true", help="Sincroniza embeddings e BM25")
    modes.add_argument("--cli", action="store_true", help="Loop interativo")
    if extended:
        modes.add_argument("--prepare-communities", action="store_true", help="Prepara resumos globais")
        modes.add_argument("--comparar", metavar="PERGUNTA", help="Executa a comparação controlada")
    parser.add_argument("--graph", action="store_true", help="Habilita extração de relações via LLM")
    parser.add_argument("--host", default="0.0.0.0", help="Host do servidor")
    parser.add_argument("--port", type=int, default=8000, help="Porta do servidor")
    return parser


def run_server(host: str, port: int) -> None:
    import uvicorn
    from logger import setup_logging
    setup_logging()
    print(f"Iniciando servidor em http://{host}:{port}")
    print(f"Documentacao interativa: http://127.0.0.1:{port}/docs\n")
    # O módulo simples usa exatamente o mesmo caminho das dependências locais.
    uvicorn.run("api:app", host=host, port=port, reload=False)


def prepare_index(base_dir: Path) -> None:
    from logger import setup_logging, get_logger
    from index_manifest import resolve_data_dir, resolve_db_dir
    from index_sync import sync_standard_index
    setup_logging()
    sync_standard_index(resolve_data_dir(str(base_dir)),
                        resolve_db_dir(str(base_dir)), get_logger(__name__))
    print("Sincronização do índice concluída.")


def main(base_dir: Path, argv: list[str] | None = None, *, extended: bool = False) -> None:
    parser = build_parser(extended=extended)
    args = parser.parse_args(argv)
    comparison = getattr(args, "comparar", None)
    if args.index_only and args.graph:
        parser.error("--index-only não pode ser combinado com --graph")
    if comparison is not None and args.graph:
        parser.error("--comparar não pode ser combinado com --graph")
    if comparison is not None and not comparison.strip():
        parser.error("Informe uma pergunta não vazia para --comparar")

    base_dir = base_dir.resolve()
    activate(base_dir)
    configure_console()
    from dotenv import load_dotenv
    if comparison is not None:
        from comparacao.run import compare
        load_dotenv(base_dir.parent / "comparacao" / ".env", override=True)
        print(json.dumps(compare(comparison, "graphrag"), ensure_ascii=False, indent=2))
        return
    load_dotenv(base_dir / ".env", override=True)
    if extended:
        from comparacao.common import apply_profile
        apply_profile()
    if args.index_only:
        prepare_index(base_dir)
    elif getattr(args, "prepare_communities", False):
        from startup import initialize
        engine, _ = initialize(str(base_dir), use_graph=args.graph)
        print(f"Resumos de {engine.prepare_communities()} comunidades preparados.")
    elif args.cli:
        from rag_app.console import run_cli
        run_cli(base_dir, use_graph=args.graph)
    else:
        if args.graph:
            os.environ["RAG_USE_GRAPH"] = "1"
        run_server(args.host, args.port)
