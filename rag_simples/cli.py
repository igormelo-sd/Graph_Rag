"""Comandos do RAG simples: o mesmo preparo e a mesma recuperação da comparação, sem grafo."""
import argparse
import json

from rag_simples.rag import ROOT


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="RAG simples (sem grafo): usa o perfil, o preparo e o ranking comuns em comparacao/.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("indexar", help="Prepara o corpus uma vez e grava o índice em rag_simples/indice e graphrag/indice.")
    for name in ("perguntar", "comparar"):
        query = commands.add_parser(name, help="Responde com o RAG simples (comparar é sinônimo).")
        query.add_argument("pergunta")
    return parser


def main(argv=None) -> None:
    from dotenv import load_dotenv
    from comparacao.common import apply_profile, load_openai_key, use_implementation

    parser = build_parser()
    args = parser.parse_args(argv)
    load_dotenv(ROOT.parent / "comparacao" / ".env", override=True)
    load_openai_key()
    use_implementation("rag_simples")  # só rag_simples/src: nenhum módulo de grafo no processo
    apply_profile(strict=True)
    from comparacao.run import compare, prepare
    try:
        result = prepare() if args.command == "indexar" else compare(args.pergunta, "rag_simples")
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Erro: {exc}\n")
    if args.command == "indexar":
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(result["answer"])
    print("\nFontes recuperadas:")
    for position, item in enumerate(result["sources"], start=1):
        page = f", página {item['page']}" if item.get("page") else ""
        print(f"[{position}] {item['source']}{page}")
