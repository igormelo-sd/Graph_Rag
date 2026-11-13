# Graph_Rag — RAG Estatístico SP

Sistema de perguntas e respostas sobre a economia do Estado de São Paulo, a partir das
publicações e bases estatísticas do corpus em `data/`.

O repositório reúne uma implementação GraphRAG, um RAG simples e uma comparação
experimental entre os dois. Organização completa e execução de todas as suítes:
[guia de manutenção](docs/REFATORACAO.md).

| Pasta | Conteúdo |
|---|---|
| `graph_rag/` | RAG com grafo: ingestão, índice híbrido, retrievers, grafo, ontologia, síntese, validação e API ([README](graph_rag/README.md)) |
| `simple_rag/` | O mesmo RAG sem nenhum módulo de grafo; índice JSON e busca por cosseno ([README](simple_rag/README.md)) |
| `data/` | Corpus compartilhado pelas duas implementações |
| `rag_app/` | Infraestrutura comum: comandos, bootstrap, terminal, proveniência, resultados, busca tabular e vínculo numérico |
| `comparacao/` | Perfil e pipeline comuns para comparar `simple_rag` e `graph_rag` ([README](comparacao/README.md)) |
| `tests_shared/` | Suíte da infraestrutura comum |

`graph_rag/` e `simple_rag/` usam `rag_app/` e `comparacao/`; mantenha a pasta completa. A raiz não tem código de RAG: cada implementação tem o próprio `src/`.

A antiga aplicação principal (`src/` e `tests/` na raiz) foi removida. O último estado
com ela está na tag `tcc-congelamento`; a variante `principal` de
`comparacao/avaliacao/experimento.py` só funciona nesse estado.

## Estrutura

```
main.py  start.bat      # atalhos para graph_rag/main.py e graph_rag/start.bat
requirements*.in/.txt  .env.example  LICENSE
data/                   # corpus compartilhado
graph_rag/              # RAG com grafo (main.py, src/, tests/, config/, docs/ próprios)
simple_rag/             # RAG sem grafo (main.py, src/ sem módulos de grafo, tests/)
rag_app/                # infraestrutura comum às implementações
comparacao/             # perfil, variantes e avaliação experimental
.agents/                # helper legado + skills de domínio no nível do repositório
scripts/                # test_all.py, lock_dependencies.ps1
docs/                   # guia de manutenção
tests_shared/
```

## Instalação

Python 3.13 / Windows x64 para o conjunto de dependências fixadas. No PowerShell, na raiz:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.txt
Copy-Item .env.example .env
```

A comparação lê a chave do `.env` da raiz; o GraphRAG carrega `graph_rag/.env`. Configuração,
índice e API estão no [README do GraphRAG](graph_rag/README.md).

## Como rodar

Cada implementação roda em processo separado:

```powershell
.\.venv\Scripts\python.exe graph_rag/main.py --cli
.\.venv\Scripts\python.exe simple_rag/main.py --cli
.\.venv\Scripts\python.exe comparacao/run.py --help
```

Comparação (detalhes em [comparacao/README.md](comparacao/README.md)): `preparar` gera o índice uma vez nas duas pastas;
`avaliar --versoes simple_rag` e `avaliar --versoes graph_rag` rodam cada versão em seu processo, na mesma `--saida`.

`main.py` e `start.bat` na raiz repassam para `graph_rag/main.py` e `graph_rag/start.bat`.

## Testes

Instale antes `pip install --require-hashes -r requirements-dev.txt`. Cada suíte roda em processo separado (`shared`, `graph_rag`, `simple_rag_src`, `simple_rag`, `comparacao`):

```powershell
.\.venv\Scripts\python.exe scripts/test_all.py
.\.venv\Scripts\python.exe scripts/test_all.py --suite shared --suite graph_rag
```

Não colete as pastas `tests` em conjunto: há arquivos e módulos homônimos entre as implementações. As suítes usam modelos simulados e não demonstram qualidade semântica em produção.

## Estado de verificação

A presença das suítes não demonstra que passaram, e a resolução dos locks (alvo Python 3.13/Windows) não comprova compatibilidade do aplicativo. O registro do que foi executado na refatoração está em [REFATORACAO.md](docs/REFATORACAO.md).

## Licença

MIT — ver `LICENSE`.
