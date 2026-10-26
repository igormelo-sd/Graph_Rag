"""Comandos do RAG simples: indexar, perguntar e comparar."""
import argparse
import json
import os
from pathlib import Path

from rag_simples.rag import ROOT, SimpleRAG


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RAG tradicional: documentos -> trechos -> vetores -> busca -> resposta.")
    parser.add_argument("--indice", type=Path, default=ROOT / "indice" / "index.json")
    commands = parser.add_subparsers(dest="command", required=True)
    index = commands.add_parser("indexar", help="Cria ou substitui o índice completo.")
    index.add_argument("--documentos", type=Path, default=Path(os.getenv("RAG_DATA_DIR") or "."))
    index.add_argument("--tamanho", type=int, default=int(os.environ["RAG_CHUNK_SIZE"]))
    index.add_argument("--sobreposicao", type=int, default=int(os.environ["RAG_CHUNK_OVERLAP"]))
    query = commands.add_parser("perguntar", help="Busca trechos e responde à pergunta.")
    query.add_argument("pergunta")
    query.add_argument("--top-k", type=int, default=int(os.environ["RAG_RETRIEVAL_TOP_K"]))
    query.add_argument("--somente-busca", action="store_true", help="Exibe trechos sem chamar o LLM.")
    comparison = commands.add_parser("comparar", help="Usa o corpus e o perfil experimental compartilhados.")
    comparison.add_argument("pergunta")
    return parser


def print_sources(results: list[dict], with_text: bool) -> None:
    print("\nFontes recuperadas (similaridade não é uma probabilidade):")
    for i, item in enumerate(results, start=1):
        page = f", página {item['page']}" if item["page"] else ""
        print(f"[{i}] {item['source']}{page}, trecho {item['number']} — {item['score']:.3f}")
        if with_text:
            print(item["text"] + "\n")


def main(argv=None) -> None:
    from dotenv import load_dotenv
    from comparacao.common import apply_profile

    load_dotenv(ROOT / ".env")
    apply_profile()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "comparar":
        load_dotenv(ROOT.parent / "comparacao" / ".env", override=True)
        from comparacao.run import compare
        print(json.dumps(compare(args.pergunta, "rag_simples"), ensure_ascii=False, indent=2))
        return
    if args.command == "indexar" and not args.documentos.is_dir():
        parser.error(f"Diretório de documentos inexistente: {args.documentos}")
    rag = SimpleRAG(args.indice, os.environ["RAG_EMBED_MODEL"], os.environ["RAG_LLM_MODEL"])
    try:
        if args.command == "indexar":
            count = rag.index(args.documentos, args.tamanho, args.sobreposicao)
            print(f"Índice criado com {count} trechos em {args.indice}.")
            return
        results = rag.search(args.pergunta, args.top_k)
        if not args.somente_busca:
            print(rag.answer(args.pergunta, results))
        print_sources(results, with_text=args.somente_busca)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Erro: {exc}\n")
