# Graph_Rag — orientações do repositório

Leia também [.agents/AGENTS.md](.agents/AGENTS.md) ao alterar skills. Este é um repositório independente; não pressupõe variantes ou arquivos Docker em diretórios superiores.

## Arquitetura

- `graphrag/`: aplicação GraphRAG com `main.py`, `src/`, `tests/`, `data/`, `config/` e `docs/` próprios. Ao alterar código dela, siga [graphrag/AGENTS.md](graphrag/AGENTS.md).
- `rag_simples/`: RAG sem grafo, com índice JSON e cosseno exato.
- `rag_app/`: infraestrutura comum. Importa módulos de `src/` pelo nome curto; `rag_app.bootstrap.activate` resolve esses nomes na pasta `src` da implementação ativada.
- `comparacao/`: perfil, variantes e avaliação experimental entre `rag_simples` e `graphrag`.
- `main.py` e `start.bat` da raiz são atalhos para `graphrag/main.py` e `graphrag/start.bat`.

A antiga aplicação principal (`src/` e `tests/` da raiz) foi removida; o último estado com ela está na tag `tcc-congelamento`.

## Convenções

Preserve alterações locais existentes. Use a factory do aplicativo para chamadas LLM. Ao alterar o contrato da resposta, mantenha API e documentação alinhadas. Nas skills de domínio, preserve os marcadores `rag-context` e as seções consumidas pelo código: esse conteúdo pode ser injetado na síntese em produção.

Não edite manualmente `chroma_db/`, `graph_store/` ou `__pycache__/`. Mudanças de processamento exigem atenção ao fingerprint do pipeline e à compatibilidade do manifesto.

A configuração usada no TCC está congelada: não altere `comparacao/`, `rag_simples/`, `rag_app/`, `graphrag/src`, `comparacao/config.json` nem as perguntas sem novo registro de congelamento. Veja [comparacao/README.md](comparacao/README.md).

## Dependências e execução

As entradas editáveis são `requirements.in` e `requirements-dev.in`. Os locks `.txt` têm hashes e alvo Windows x64/Python 3.11; `scripts/lock_dependencies.ps1` permite regenerá-los deliberadamente. Consulte [README.md](README.md) para instalação e execução.

Respeite instruções explícitas de não executar testes, servidor, avaliações ou validadores. A presença de uma suíte não demonstra que ela passou. Execute cada suíte em processo separado com `scripts/test_all.py`.
