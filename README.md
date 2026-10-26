# Graph_Rag — RAG Estatístico SP (Principal / Híbrido)

Sistema de perguntas e respostas sobre a economia do Estado de São Paulo, a partir das
publicações e bases estatísticas em `data/`. Retrieval **híbrido (Vector + BM25)** sobre
texto, mais retrievers de **tabelas**, **séries temporais**, **imagens** e **grafo de
conhecimento**, com rerank, validação numérica e API FastAPI.

O repositório reúne a aplicação principal (raiz), uma variante GraphRAG, um RAG simples e
uma comparação experimental entre os dois últimos. Organização completa e execução de
todas as suítes: [guia de manutenção](docs/REFATORACAO.md).

| Pasta | Conteúdo |
|---|---|
| `src/` | Aplicação principal: ingestão, índice, retrievers, síntese, validação e API |
| `rag_app/` | Infraestrutura comum: comandos, bootstrap, terminal, proveniência, resultados, busca tabular e vínculo numérico |
| `graphrag/` | Variante com expansão por entidades, pais textuais e busca global por comunidades ([README](graphrag/README.md)) |
| `rag_simples/` | RAG tradicional sem grafo, índice JSON e busca exata por cosseno ([README](rag_simples/README.md)) |
| `comparacao/` | Perfil e pipeline comuns para comparar `rag_simples` e `graphrag` ([README](comparacao/README.md)) |
| `tests/`, `tests_shared/` | Suítes da aplicação principal e da infraestrutura comum |

`graphrag/` e `rag_simples/` usam os componentes comuns da raiz; mantenha a pasta completa.

## Arquitetura

```
Pergunta → interpret_query (LLM leve) → AnalysisEngine (retrievers em paralelo) → seleção global → síntese (LLM) → validações → resposta + fontes
```

| Componente | Arquivo | Papel |
|---|---|---|
| Entrada | `main.py` → `rag_app/cli.py` | Servidor (padrão), chat (`--cli`) ou só índice (`--index-only`); `--graph` habilita extração via LLM |
| Bootstrap | `rag_app/bootstrap.py`, `src/startup.py:initialize` | Ativa a pasta da implementação → resolve caminhos → índice portátil → `sync_standard_index` → LLMs → retrievers + reranker + skills + engine |
| Interpretação | `src/query_interpreter.py` | LLM decide `sources`, `rewritten_query`, `is_labor_market` |
| Síntese | `src/analysis_engine.py`, `src/query_service.py` | Retrievers em paralelo, síntese e resultado por consulta |
| Seleção | `src/rag_selection.py` | RRF global, cobertura candidata, contexto indivisível e células literais |
| Texto | `src/text_retriever.py` | Híbrido VectorIndex + BM25 + rerank e diversificação |
| Tabelas / séries | `src/tables_retriever.py`, `src/timeseries_retriever.py`, `src/structured_lookup.py` | Recuperação de células, busca tabular e cálculos Decimal por planos JSON (`src/calculations.py`) |
| Imagens | `src/images_retriever.py` | Nós `type=image` |
| Grafo | `src/graph_indexing.py`, `src/graph_retriever.py`, `src/graph_ontology.py` | Estrutural por padrão (`RAG_GRAPH_STRUCT=1`); embedding com `RAG_GRAPH_EMBED=1`; extração LLM com `--graph` |
| Ontologia | `src/domain_ontology.py`, `src/ontology_extractor.py`, `src/statistical_observations.py`, `src/knowledge_analytics.py` | Conceitos, observações candidatas, cobertura, divergências e esclarecimentos |
| Validação | `src/numerical_validator.py`, `src/numeric_binding.py`, `src/citation_validator.py`, `src/evidence.py` | Correspondência contextual por ocorrência e citações explícitas |
| API | `src/api.py` | FastAPI + lifespan; segurança (`src/api_security.py`), modelos (`src/api_models.py`), métricas (`src/metrics.py`), carga (`src/load_control.py`) |
| LLMs | `src/llm.py` | Factory do aplicativo; um provedor ativo, sem troca automática após erro |
| Ingestão | `src/ingestion.py`, `src/processing.py`, `src/indexing.py`, `src/index_sync.py`, `src/index_manifest.py` | Fontes → nós (`text|table|image`) → Chroma + `bm25_nodes.pkl` + manifesto |
| Skills | `src/domain_skills.py`, `src/labor_market_skill.py`, `.agents/skills/` | Skills de domínio (mercado de trabalho, conjuntura, investimento e comércio, setorial/regional) |

Embeddings: o padrão do código é `huggingface` com `BAAI/bge-m3` (local); o `.env.example`
usa o Ollama com `embeddinggemma:300m` (ver [Embeddings pelo Ollama](#embeddings-pelo-ollama)).
Rerank padrão: cross-encoder local `BAAI/bge-reranker-v2-m3` (`RAG_BGE_RERANK=1`), com
fallback para `LLMRerank` ou `ScoreReranker`.

### Seleção final de evidências

A recuperação usa fusão global, cobertura dos recortes pedidos, blocos completos de
contexto e reutilização de células literais. `retrieval_coverage` não prova suficiência
nem compatibilidade metodológica. Veja [Melhorias do RAG](docs/MELHORIAS_RAG.md). Alterações
no splitter mudam o fingerprint e exigem reconstrução dos índices.

## Ontologia de domínio

O modelo compartilhado atua na ingestão, busca, interpretação, cálculos e evidências, além do grafo. Distingue estado e município, períodos, unidades e natureza das medidas. Observações candidatas mantêm proveniência; relações LLM exigem tipos compatíveis e citação literal.

A API inclui `ontology` com dimensões da pergunta, observações e auditorias disponíveis. `RAG_ONTOLOGY_ENABLE=1` habilita observações, prompts e filtros. Novas classes descobertas são propostas; só entram após revisão em `config/ontology_extensions.json` (ou `RAG_ONTOLOGY_EXTENSIONS`). Veja [Ontologia](docs/ONTOLOGIA.md).

Observações por célula preservam cabeçalho, linha, título/notas e datas de publicação separadas. A recuperação percorre arestas documentais e registra os caminhos. A API também retorna `clarification` para ambiguidades e `knowledge` para cobertura/divergências; `ontology.comparisons` contém o grafo dos cálculos, isolado por consulta. Cálculos e divergências não são promovidos a fatos do corpus. Veja [Estatísticas e grafos](docs/ESTATISTICAS_GRAFO.md).

## Estrutura

```
main.py  start.bat  requirements*.in/.txt  .env.example  LICENSE
src/            # aplicação principal
rag_app/        # infraestrutura comum às implementações
graphrag/       # variante GraphRAG (main.py, src/, tests/, data/ próprios)
rag_simples/    # RAG simples sem grafo
comparacao/     # perfil, variantes e avaliação experimental
.agents/        # helper legado + skills de domínio
config/         # extensões revisadas da ontologia
data/           # corpus indexado: 7 PDF, 3 XLSX e 11 CSV
data_fonte/     # catálogo de origem (fontes.json); não indexado
evaluation/     # exemplos de casos; não são resultados experimentais
scripts/        # test_all.py, evaluate_retrieval.py, index_artifact.py, lock_dependencies.ps1
docs/           # documentação técnica
tests/  tests_shared/
chroma_db/      # gerado: chroma.sqlite3 + bm25_nodes.pkl + indexed_manifest.json
.cache/         # gerado: cache de embeddings e checkpoint de nós
```

## Pré-requisitos

- Python 3.11 / Windows x64 para o conjunto de dependências fixadas (`.venv` recomendado); espaço e memória dependem dos modelos e do corpus
- Chave de LLM no `.env` — padrão OpenAI (`OPENAI_API_KEY`); OpenRouter (`OPENROUTER_API_KEY`) ou Ollama local como alternativa
- Ollama em execução se `RAG_EMBED_PROVIDER=ollama` (configuração do `.env.example`)

## Como rodar

### Inicialização rápida no Windows

Depois de instalar as dependências e configurar `.env`, execute `start.bat` com duplo clique ou no PowerShell:

```powershell
.\start.bat
```

O inicializador usa o Python de `.venv`, abre o chat no terminal e deixa o bootstrap conferir o índice e o manifesto. Se não houver embeddings, eles são criados antes do chat; se existirem, são reutilizados, sincronizando arquivos novos, alterados ou removidos. Digite `sair` para encerrar. Em caso de erro, a janela permanece aberta. O script não instala dependências e pode baixar modelos locais no primeiro uso.

O `start.bat` habilita sincronização (`RAG_INDEX_READ_ONLY=0`) e desabilita download de índice pronto (`RAG_INDEX_AUTO_DOWNLOAD=0`). A pasta padrão é `data`; `RAG_DATA_DIR`, se configurada, tem precedência. O `.env` da implementação é carregado com `override=True`: valores definidos nele prevalecem sobre o ambiente, inclusive sobre os definidos pelo `start.bat`.

O `.env` local está organizado com OpenRouter ativo e `openrouter/free` nos modelos de resposta, interpretação e explicação; o modelo efetivo pode variar entre chamadas e está sujeito aos limites do serviço ([roteador gratuito do OpenRouter](https://openrouter.ai/openrouter/free)). As chaves NVIDIA e Gemini não são consumidas pela factory atual, e `CODEX_MODEL` não configura o modelo do RAG. Não há fallback automático entre provedores.

### Instalação e comandos individuais

No PowerShell, na raiz do Graph_Rag:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.txt
Copy-Item .env.example .env
```

Preencha o provedor de linguagem no `.env`. Escolha a pasta do corpus e permita sua sincronização:

```powershell
$env:RAG_DATA_DIR = "$PWD\data"
$env:RAG_INDEX_READ_ONLY = "0"
```

Somente embeddings e BM25, sem chat ou servidor (não constrói o grafo):

```powershell
.\.venv\Scripts\python.exe main.py --index-only
```

Para o caminho padrão local, mantenha `RAG_INGEST_LLM_ENRICHMENT=0` e `RAG_RAPTOR_ENABLE=0`. Fontes removidas deixam de integrar o índice, fontes alteradas são reprocessadas e mudanças na versão do processamento provocam reindexação; não é necessário apagar o banco.

Chat no terminal (digite `sair` para encerrar):

```powershell
.\.venv\Scripts\python.exe main.py --cli
```

API, com documentação em http://localhost:8080/docs (sem argumentos: `0.0.0.0:8000`):

```powershell
.\.venv\Scripts\python.exe main.py --host 127.0.0.1 --port 8080
```

CLI e API também sincronizam o índice ao iniciar. Extração de relações por LLM e embeddings do grafo:

```powershell
$env:RAG_GRAPH_EMBED = "1"
.\.venv\Scripts\python.exe main.py --cli --graph
```

`--graph` usa o provedor configurado e pode consumir API. `--index-only` e `--cli` são mutuamente exclusivos, e `--index-only` não aceita `--graph`. Os argumentos são validados antes de carregar modelos, e `--help` funciona sem as dependências de aprendizado de máquina.

As outras implementações, a partir da raiz e em processos separados:

```powershell
.\.venv\Scripts\python.exe graphrag/main.py --cli
.\.venv\Scripts\python.exe rag_simples/rag.py --help
.\.venv\Scripts\python.exe comparacao/run.py --help
```

### Preparação dos arquivos

- Formatos: PDF, CSV, XLSX, XLS e TXT, incluindo subpastas de `data`.
- CSV: BOM UTF-16, UTF-8 e fallback Windows-1252; separador detectado entre ponto e vírgula, vírgula e tabulação. Códigos, zeros iniciais e vírgulas decimais são preservados como texto. Linhas inconsistentes interrompem a ingestão em vez de omitir a fonte silenciosamente.
- Tabelas: um trecho por linha, com teto de `RAG_TABLE_MAX_ROWS_PER_TABLE` (padrão 1.000) linhas por tabela; as linhas excedentes não recebem embedding. No corpus atual, `pib_municipal_2002_2020.csv` e as bases `base-pim/pmc/pms_spbrasil.csv` ultrapassam esse teto.
- XLSX: expande somente mesclagens declaradas, preserva títulos e combina linhas de cabeçalho anteriores aos dados. A identificação da primeira linha de dados é heurística e marcada para revisão (`table_context_requires_review`). XLS usa a mesma heurística, sem expansão de mesclagens.
- Excel usa valores armazenados; não recalcula fórmulas. Células sem resultados salvos precisam ser recalculadas e salvas no aplicativo de origem.
- `data_fonte/fontes.json` documenta a origem. JSON e Markdown não são indexados; os links desse catálogo ainda não são incorporados às citações.

### Testes

Instale antes `pip install --require-hashes -r requirements-dev.txt`. Cada suíte roda em processo separado (`shared`, `principal`, `graphrag`, `simples`, `comparacao`):

```powershell
.\.venv\Scripts\python.exe scripts/test_all.py
.\.venv\Scripts\python.exe scripts/test_all.py --suite shared --suite principal
```

Não colete as pastas `tests` em conjunto: há arquivos e módulos homônimos entre as implementações. As suítes usam modelos simulados e não demonstram qualidade semântica em produção.

## API

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/query` | `{"question": "..."}` → `{answer, sources, validation, ...}` |
| `GET` | `/knowledge` | Cobertura e divergências candidatas do corpus; `question` opcional; sem LLM |
| `GET` | `/health` | Engine + Chroma + BM25 + embedding (`ok`/`degraded`/`starting`) |
| `GET` | `/metrics` | Métricas Prometheus |
| `GET` | `/docs` | Swagger interativo |
| `GET` | `/app` | Frontend estático (se `frontend/dist` existir) |

Exemplo:

```powershell
curl -Method Post http://127.0.0.1:8080/query `
  -Headers @{"Content-Type"="application/json"} `
  -Body '{"question":"Como evoluiu a indústria farmacêutica paulista?"}'
```

Resposta (`src/api_models.py:QueryResponse`): `answer`, `sources_used`, `rewritten_query`,
`sources[]` (`file`, `score`, `page`, `excerpt`, `row?`, `sheet?`, `cells[]`), `validation`/`citation_validation`
(`verified/total/unverified`), `numeric_citations[]`, `claim_evidence`, `calculations`, `ontology`, `clarification`, `knowledge`, `usage`, `rag_type`, `rag_label`, `timeseries_chart?`. A validação numérica informa também `method` e `requires_review`.

## Configuração (`.env`)

| Variável | Padrão | Efeito |
|---|---|---|
| `RAG_LLM_PROVIDER` | `openai` | `openai` \| `openrouter` \| `ollama` (endpoint compatível via overrides) |
| `RAG_LLM_MODEL` / `RAG_INTERP_MODEL` / `RAG_POPUP_MODEL` | `gpt-5-chat-latest` / `gpt-5-mini` / `gpt-5-mini` | Síntese / interpretação-rerank / explicações de citação |
| `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `RAG_LLM_API_KEY`, `RAG_LLM_BASE_URL` | — | Chave do provedor ativo ou overrides explícitos, sem fallback automático |
| `RAG_LLM_CONCURRENCY` / `RAG_MAX_OUTPUT_TOKENS` | — | Limite de chamadas simultâneas / teto de tokens de saída |
| `RAG_EMBED_PROVIDER` / `RAG_EMBED_MODEL` | `huggingface` / `BAAI/bge-m3` | `huggingface` \| `ollama`; o `.env.example` usa `ollama` / `embeddinggemma:300m` |
| `RAG_EMBED_BATCH_SIZE` / `RAG_OLLAMA_EMBED_URL` | — / `http://127.0.0.1:11434` | Lote e endpoint do Ollama |
| `RAG_CHUNK_SIZE` / `RAG_CHUNK_OVERLAP` | `1024` / `200` | Chunking |
| `RAG_SMALL_TABLE_MAX_ROWS` / `RAG_TABLE_MAX_ROWS_PER_TABLE` | `10` / `1000` | Tabelas pequenas tratadas inteiras / teto de linhas indexadas por tabela |
| `RAG_BGE_RERANK` / `RAG_LLM_RERANK` | `1` / `1` | Cross-encoder local / rerank por LLM |
| `RAG_INDEX_AUTO_DOWNLOAD` / `RAG_INDEX_READ_ONLY` | `0` / `0` | Baixa índice portátil do release / congela índice (`=1`) |
| `RAG_GRAPH_STRUCT` / `RAG_GRAPH_EMBED` / `RAG_USE_GRAPH` | `1` / `0` / — | Estrutura sem extração LLM / embedding do grafo / extração por LLM |
| `RAG_ONTOLOGY_ENABLE` / `RAG_ONTOLOGY_EXTENSIONS` | — | Observações e filtros da ontologia / arquivo de extensões revisadas |
| `RAG_VISION` / `RAG_RAPTOR_ENABLE` / `RAG_INGEST_LLM_ENRICHMENT` | `0` | Flags experimentais/desligadas |

As variáveis de tabela e embedding entram no fingerprint do pipeline: alterá-las exige reconstruir o índice.

## Índice

- O primeiro boot (re)indexa `data/` → `chroma_db/` (`chroma.sqlite3`, `bm25_nodes.pkl` e `indexed_manifest.json`); tamanho e tempo dependem do corpus e da máquina.
- Boots seguintes detectam mudanças por mtime (`sync_standard_index`) e só reindexam o necessário.
- Os IDs dos nós consideram o conteúdo completo. Mudanças de esquema, splitter, ontologia ou embeddings alteram o fingerprint e exigem reconstrução na próxima inicialização com `RAG_INDEX_READ_ONLY=0`.
- A promoção da coleção Chroma ocorre em etapas; o cache BM25 e o manifesto são atualizados depois de concluir e validar a coleção nova, sem transação atômica conjunta.
- Para congelar: `RAG_INDEX_READ_ONLY=1`. Para usar o artefato de release: `RAG_INDEX_AUTO_DOWNLOAD=1`, com `RAG_INDEX_REPO=proprietario/repositorio`, `RAG_INDEX_TAG` (padrão `index-v1`) e `RAG_INDEX_ASSET` (padrão `graph-rag-index.tar.gz`). Não existe release remota presumida.
- `scripts/index_artifact.py` exporta e instala o formato local com manifesto e SHA-256; exporte com o servidor parado. Use apenas artefatos confiáveis, pois o cache BM25 contém pickle. Downloads autenticados não são suportados.
- `chroma_db/`, `graph_store/`, `.cache/`, `__pycache__/` são gerados — não editar nem versionar.

### Embeddings pelo Ollama

Baixe `embeddinggemma:300m` no Ollama e configure:

```dotenv
RAG_EMBED_PROVIDER=ollama
RAG_EMBED_MODEL=embeddinggemma:300m
RAG_EMBED_BATCH_SIZE=16
RAG_OLLAMA_EMBED_URL=http://127.0.0.1:11434
```

O Ollama deve estar em execução; o aplicativo verifica o modelo antes de extrair as fontes. Para voltar ao padrão local, use `RAG_EMBED_PROVIDER=huggingface` e `RAG_EMBED_MODEL=BAAI/bge-m3`. A troca de provedor, modelo ou digest exige reconstruir os vetores.

O cache `.cache/embeddings.sqlite3` salva cada lote de inferência, com chaves que incluem conteúdo, tipo de entrada (consulta/documento), modelo, digest e política de segmentação; na retomada, os vetores já calculados são reaproveitados. O checkpoint `.cache/processed_nodes.pkl` evita repetir extração e processamento quando corpus e pipeline não mudaram. Esses arquivos podem conter informações do corpus e não devem ser versionados.

Entradas longas são divididas em segmentos de até 2.000 caracteres, enviados com `truncate=false`; segmentos que ainda excedem o limite de tokens são divididos novamente. Os segmentos compõem uma média ponderada normalizada, e o texto original permanece no índice. Essa agregação pode diluir a relevância de entradas com vários assuntos.

## Desenvolvimento

- `--graph` funciona no CLI e no servidor; `RAG_USE_GRAPH=1` também ativa extração via LLM. Mudanças no modo do grafo invalidam seu cache na próxima inicialização.
- Gráficos são retornados junto ao resultado de cada consulta, sem estado compartilhado. O timeout HTTP abrange interpretação, busca, síntese e validação; chamadas síncronas já iniciadas em threads podem terminar em segundo plano após o cancelamento.
- A validação numérica exige correspondência contextual conservadora por ocorrência; correspondências heurísticas não são prova semântica. Cálculos são executados em Decimal a partir de planos JSON limitados; `safe_exec.py` é um utilitário legado, fora do fluxo atual. Veja [Confiabilidade, carga e avaliação](docs/CONFIABILIDADE.md).
- Prompts/rerank: `src/query_interpreter.py` + `src/analysis_engine.py` (modelos sempre via factory, sem hard-code).
- Novo retriever: seguir o padrão `text/tables/timeseries_retriever.py`, registrar a fonte no `query_interpreter` e passar a `engine.answer`.
- Os módulos `runtime`, `provenance` e `query_results` de `src/` reexportam a implementação comum de `rag_app/`.
- Avaliação: `scripts/evaluate_retrieval.py` exige gabaritos revisados; os exemplos em `evaluation/` não são resultados.
- Detalhes por módulo: [PYTHON.md](docs/PYTHON.md), [COMO_FUNCIONA.md](COMO_FUNCIONA.md) e [AGENTS.md](AGENTS.md).

## Estado de verificação

A presença das suítes não demonstra que passaram, e a resolução dos locks (alvo Python 3.11/Windows) não comprova compatibilidade do aplicativo. O registro do que foi executado na refatoração está em [REFATORACAO.md](docs/REFATORACAO.md).

## Licença

MIT — ver `LICENSE`.
