# Graph_Rag — RAG Estatístico SP

Sistema de perguntas e respostas sobre a economia do Estado de São Paulo, a partir das
publicações e bases estatísticas do corpus em `graphrag/data/`.

O repositório reúne uma implementação GraphRAG, um RAG simples e uma comparação
experimental entre os dois. Organização completa e execução de todas as suítes:
[guia de manutenção](docs/REFATORACAO.md).

| Pasta | Conteúdo |
|---|---|
| `graphrag/` | Aplicação GraphRAG: ingestão, índice híbrido, retrievers, grafo, ontologia, síntese, validação e API ([README](graphrag/README.md)) |
| `rag_simples/` | RAG tradicional sem grafo, índice JSON e busca exata por cosseno ([README](rag_simples/README.md)) |
| `rag_app/` | Infraestrutura comum: comandos, bootstrap, terminal, proveniência, resultados, busca tabular e vínculo numérico |
| `comparacao/` | Perfil e pipeline comuns para comparar `rag_simples` e `graphrag` ([README](comparacao/README.md)) |
| `tests_shared/` | Suíte da infraestrutura comum |

`graphrag/` e `rag_simples/` usam os componentes comuns da raiz; mantenha a pasta completa.

A antiga aplicação principal (`src/` e `tests/` na raiz) foi removida. O último estado
com ela está na tag `tcc-congelamento`; a variante `principal` de
`comparacao/avaliacao/experimento.py` só funciona nesse estado.

## Estrutura

```
main.py  start.bat      # atalhos para graphrag/main.py e graphrag/start.bat
requirements*.in/.txt  .env.example  LICENSE
graphrag/               # aplicação GraphRAG (main.py, src/, tests/, data/, config/, docs/ próprios)
rag_simples/            # RAG simples sem grafo
rag_app/                # infraestrutura comum às implementações
comparacao/             # perfil, variantes e avaliação experimental
.agents/                # helper legado + skills de domínio no nível do repositório
scripts/                # test_all.py, lock_dependencies.ps1
docs/                   # guia de manutenção
tests_shared/
```

## Instalação

Python 3.11 / Windows x64 para o conjunto de dependências fixadas. No PowerShell, na raiz:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.txt
Copy-Item .env.example .env
```

A comparação lê a chave do `.env` da raiz; o GraphRAG carrega `graphrag/.env`. Configuração,
índice e API estão no [README do GraphRAG](graphrag/README.md).

## Como rodar

Cada implementação roda em processo separado:

```powershell
.\.venv\Scripts\python.exe graphrag/main.py --cli
.\.venv\Scripts\python.exe rag_simples/rag.py --help
.\.venv\Scripts\python.exe comparacao/run.py --help
```

`main.py` e `start.bat` na raiz repassam para `graphrag/main.py` e `graphrag/start.bat`.

## Testes

Instale antes `pip install --require-hashes -r requirements-dev.txt`. Cada suíte roda em processo separado (`shared`, `graphrag`, `simples`, `comparacao`):

```powershell
.\.venv\Scripts\python.exe scripts/test_all.py
.\.venv\Scripts\python.exe scripts/test_all.py --suite shared --suite graphrag
```

Não colete as pastas `tests` em conjunto: há arquivos e módulos homônimos entre as implementações. As suítes usam modelos simulados e não demonstram qualidade semântica em produção.

## Estado de verificação

A presença das suítes não demonstra que passaram, e a resolução dos locks (alvo Python 3.11/Windows) não comprova compatibilidade do aplicativo. O registro do que foi executado na refatoração está em [REFATORACAO.md](docs/REFATORACAO.md).

## Licença

MIT — ver `LICENSE`.
