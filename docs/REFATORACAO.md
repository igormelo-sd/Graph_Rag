# Organização e manutenção do repositório

O repositório contém a implementação GraphRAG, um RAG simples e uma comparação
experimental. A antiga aplicação principal (`src/` e `tests/` da raiz) foi
removida; o último estado com ela está na tag `tcc-congelamento`. Mantenha a pasta completa: `graph_rag/`
e `simple_rag/` usam os componentes comuns da raiz.

| Pasta | Responsabilidade |
|---|---|
| `graph_rag/src/` | Aplicação GraphRAG: recuperação híbrida, API, ingestão, validação, expansão de pais e busca global por comunidades |
| `rag_app/` | Comandos, inicialização, terminal, limites, proveniência, resultados e persistência comuns |
| `rag_app/structured_lookup.py`, `numeric_binding.py` | Busca tabular completa e vínculo numérico por ocorrência usados pela aplicação GraphRAG |
| `simple_rag/src/` | O mesmo código de `graph_rag/src` sem os módulos de grafo (teste de identidade em `tests_shared/test_implementations.py`) |
| `simple_rag/chunk.py` | Trecho gravado no índice JSON |
| `simple_rag/vectors.py` | Validação, normalização e ranking exato por cosseno |
| `simple_rag/index_store.py` | Gravação atômica e validação do índice JSON |
| `simple_rag/rag.py` | Classe `SimpleRAG`: embeddings, índice, busca e resposta |
| `simple_rag/cli.py`, `simple_rag/main.py` | Comandos `indexar`, `perguntar` e `comparar`; entrada da aplicação sem grafo |
| `data/` | Corpus compartilhado pelas duas implementações |
| `comparacao/profile.py` | Validação do perfil experimental |
| `comparacao/common.py` | Aplicação do perfil, factories de modelos e contexto compartilhado |
| `comparacao/variants.py` | Estratégias comparadas: `SimpleVariant` (sem grafo) e `GraphVariant` (entidades, vizinhança, pais, comunidades) |
| `comparacao/run.py` | Preparação, validação do índice experimental e pipeline comum da comparação |
| `comparacao/retrieval.py` | Ranking inicial comum: vetorial, BM25, fusão RRF, reranking e diversificação por tabela |
| `comparacao/footnotes.py` | Linhas de rodapé das planilhas convertidas em notas da tabela no preparo |
| `comparacao/chunk_repair.py` | Fragmentos curtos anexados ao trecho anterior e tabelas pequenas reunidas no preparo |
| `tests_shared/` | Regressões da infraestrutura compartilhada |

## Execução

Os comandos existentes continuam disponíveis a partir da raiz:

```powershell
.\.venv\Scripts\python.exe graph_rag/main.py --cli
.\.venv\Scripts\python.exe simple_rag/rag.py --help
.\.venv\Scripts\python.exe comparacao/run.py --help
```

`graph_rag/main.py` delega para `rag_app.cli`; o `main.py` da raiz é só um
atalho para ele. Os argumentos são validados antes
de carregar modelos, credenciais ou índices. `--help` funciona sem carregar as
dependências de aprendizado de máquina. Cada implementação lê seu próprio
`.env`, independentemente do diretório corrente.

As implementações ainda usam imports locais legados. `rag_app.bootstrap`
prioriza a pasta selecionada e rejeita módulos previamente carregados de outra
origem. Execute as variantes em processos separados. Isso também impede que a
comparação reutilize silenciosamente o código da aplicação principal.

## Testes

```powershell
.\.venv\Scripts\python.exe scripts/test_all.py
.\.venv\Scripts\python.exe scripts/test_all.py --suite shared --suite comparacao
```

O executor roda as quatro suítes em processos separados e retorna erro se qualquer
uma falhar. Não use coleta conjunta das duas pastas `tests`: elas têm arquivos
homônimos e importam módulos locais com os mesmos nomes.

As suítes usam modelos simulados e não demonstram qualidade semântica em produção.
O ambiente utilizado nesta refatoração é Python 3.13; os locks existentes têm
como alvo Python 3.11/Windows. Foi necessário instalar `langchain-text-splitters`
1.1.3 no ambiente local para executar os testes da antiga aplicação principal. Os locks
não foram regenerados nesta refatoração.

## Compatibilidade

- Os módulos `runtime`, `provenance` e `query_results` de `graph_rag/src`
  reexportam a implementação comum, preservando os imports dos consumidores.
- A numeração de trechos por fonte/página foi centralizada sem mudar agrupamento,
  ordem, conteúdo, splitter ou fingerprint do pipeline.
- A persistência do índice JSON simples utiliza temporários exclusivos e
  substituição atômica; uma falha de serialização preserva o arquivo anterior.
- Perfil inválido informa o campo correspondente antes da criação dos modelos.
- Os testes de contrato usam território explícito e nós com conteúdo; as regras
  de validação numérica e territorial de produção permanecem as mesmas.

Não houve migração do corpus nem reconstrução dos índices. A duplicação restante
entre os motores exige tratamento por subsistema: processamento, indexação,
retrieval e síntese têm diferenças que não devem ser eliminadas automaticamente.

## Comparação simplificada

A comparação oferece somente `simple_rag` e `graph_rag`, com nomes iguais aos das
pastas. `graph_rag/main.py --comparar "pergunta"` usa automaticamente entidades,
estrutura, pais e, para perguntas globais, comunidades. Não existe modo reduzido
nem argumento adicional para selecionar uma versão completa.

Em `comparacao/run.py`, o pipeline é o mesmo para as duas versões: valida o
índice, carrega modelos, faz a busca vetorial inicial, empacota o contexto e
sintetiza com o mesmo prompt. A única etapa que muda é `strategy.retrieve()`, em
`comparacao/variants.py`. Para testar outra estratégia, acrescente uma classe com
`graph_extraction`, `__init__(nodes, client, settings, artifacts)` e
`retrieve(question, ranked)` ao `REGISTRY`. O GraphRAG expõe
`graph_indexing.inject_deterministic_triplets()` e
`CommunitySearch.consolidate()` para que a comparação não dependa de funções
privadas.

O índice compartilhado continua compatível. IDs de trechos ausentes ou duplicados
são rejeitados antes de carregar modelos. Nas respostas globais, os IDs de fontes
candidatas se restringem aos nós efetivamente disponíveis na busca por comunidades.

A depuração também corrigiu consultas ao armazenamento do grafo com uma lista
vazia de IDs: a biblioteca tratava essa entrada como busca sem filtro. Agora,
nenhum ID produz nenhuma fonte, e os resultados são filtrados pelos IDs pedidos.
O comportamento está coberto por regressões em `graph_rag/tests`.

## Revisão de 12/11/2026

- **Nomes:** `rag_simples` → `simple_rag`, `graphrag` → `graph_rag` e `rag_pais` → `parent_rag`
  (pastas, módulos e variantes). Os registros de congelamento e o rascunho do capítulo 5
  mantêm os nomes antigos de propósito, pois descrevem resultados já obtidos. As ferramentas de
  avaliação (`cega.py`, `marcadores.py`, `cobertura.py`) leem resultados com os dois nomes
  (`comparacao/avaliacao/resultados.py`).
- **Corpus:** movido de `graphrag/data` para `data/` na raiz, compartilhado. `corpus` em
  `comparacao/config.json` mudou, o que altera o fingerprint do perfil e exige novo `preparar`.
- **`simple_rag/src`:** sem nenhum módulo de grafo; `analysis_engine`, `startup`,
  `query_interpreter`, `parent_context` e `domain_ontology` perderam os ganchos de grafo.
  Os demais módulos são idênticos aos de `graph_rag/src` (teste de identidade).
- **Fluxo antigo do RAG simples removido:** `documents.py`, `SimpleRAG.index()`, a dependência
  `pypdf` e o exemplo em `documentos/` duplicavam o preparo e usavam outro divisor de texto.
  `indexar` agora chama o mesmo `preparar` da comparação. O rótulo `embedding_backend` do
  índice deixou de dizer `huggingface-local` (o provedor vem do perfil).
- **Testes:** `scripts/test_all.py` ganhou `simple_rag_src` (a suíte de `graph_rag/tests`
  contra `simple_rag/src`; `RAG_TEST_IMPL=simple_rag`). Os testes que exigem grafo são pulados
  nesse modo. Resultado local: `graph_rag` 305 passam; `simple_rag_src` 221 passam e 13 pulados;
  `simple_rag` 7 e `comparacao` 59 passam; `tests_shared` 105 passam (inclui o hash do corpus e a identidade dos módulos). Python 3.13.
- **Depuração:** um teste apontava para o corpus no lugar antigo e foi corrigido; `pyflakes`
  não achou nomes indefinidos; foram removidos imports que ficaram mortos.
