"""Interface de terminal compartilhada; modelos carregados somente na execução."""
from pathlib import Path

def run_cli(base_dir: Path, use_graph: bool = False) -> None:
    import asyncio
    from dotenv import load_dotenv
    from startup import initialize
    from query_interpreter import interpret_query
    from numerical_validator import validate_numbers, format_validation_report

    load_dotenv(base_dir / ".env")

    engine, interp_llm = initialize(str(base_dir), use_graph=use_graph)

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
                score = round(node.score or 0, 4)
                print(f"  [{i+1}] {fname} (relevância: {score:.2f})")

        except Exception as exc:
            print(f"\n[ERRO] {exc}\n")

        print("\n" + "-" * 40 + "\n")


