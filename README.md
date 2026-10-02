# Graph_Rag — RAG Estatístico SP (Principal / Híbrido)

Sistema de perguntas e respostas sobre a economia do Estado de São Paulo, a partir dos
boletins **SP Economia (Seade)** em `data/` (10 PDFs). Retrieval **híbrido
(Vector + BM25)** sobre texto, mais retrievers de **tabelas**, **séries temporais**,
**imagens** e **grafo de conhecimento**, com rerank, validação numérica e API FastAPI.

## Arquitetura

```
Pergunta → interpret_query (LLM leve) → AnalysisEngine (retrievers em paralelo) → síntese (LLM) → validate_numbers → resposta + fontes
```

| Componente | Arquivo | Papel |
|---|---|---|
| Entrada | `main.py` | Servidor (`--port`) ou loop CLI (`--cli`); `--graph` habilita grafo via LLM |
| Bootstrap | `src/startup.py:initialize` | Resolve caminhos → índice portátil → `sync_standard_index` → LLMs → retrievers + reranker + skills + engine |
| Interpretação | `src/query_interpreter.py` | LLM decide `sources`, `rewritten_query`, `is_labor_market` |
| Síntese | `src/analysis_engine.py` | Roda retrievers em paralelo, sintetiza com o LLM |
| Texto | `src/text_retriever.py` | Híbrido VectorIndex + BM25 + rerank |
| Tabelas / séries | `src/tables_retriever.py`, `src/timeseries_retriever.py` | Recuperação de células e cálculos Decimal por planos JSON |
| Imagens | `src/images_retriever.py` | Nós `type=image` |
| Grafo | `src/graph_indexing.py`, `src/graph_retriever.py` | Estrutural por padrão (`RAG_GRAPH_STRUCT=1`); embedding com `RAG_GRAPH_EMBED=1`; extração LLM com `--graph` |
| Validação | `src/numerical_validator.py`, `src/citation_validator.py` | Correspondência contextual por ocorrência e citações explícitas |
| API | `src/api.py` | FastAPI + lifespan; segurança (`src/api_security.py`), modelos (`src/api_models.py`), métricas (`src/metrics.py`) |
| LLMs | `src/llm.py` | Factory do aplicativo; um provedor ativo, sem troca automática após erro |
| Ingestão | `src/ingestion.py`, `src/processing.py`, `src/indexing.py`, `src/index_sync.py`, `src/index_manifest.py` | PDFs → nós (`text|table|image`) → Chroma + `bm25_nodes.pkl` + manifesto |
| Skills | `src/domain_skills.py`, `src/labor_market_skill.py`, `.agents/skills/` | Skills de domínio (ex.: mercado de trabalho) |

Embeddings 100% locais: `BAAI/bge-m3` (1024 dim) via `src/indexing.py:setup_embeddings`.
Rerank padrão: cross-encoder local `BAAI/bge-reranker-v2-m3` (`RAG_BGE_RERANK=1`), com fallback para `LLMRerank` ou `ScoreReranker`.

## Estrutura

```
main.py  requirements.txt  .env  LICENSE
src/            # API, engine, retrievers, indexação, validação
.agents/        # helper legado + skills de domínio
data/           # 10 PDFs Seade (fonte indexada)
chroma_db/      # gerado no 1º boot: chroma.sqlite3 + bm25_nodes.pkl + indexed_manifest.json
tests/          # suítes pytest; execução pendente
```

## Pré-requisitos

- Python 3.11 / Windows x64 para o conjunto de dependências fixadas (.venv recomendado); espaço e memória dependem dos modelos e do corpus
- Chave de LLM no `.env` — padrão OpenAI (`OPENAI_API_KEY`); OpenRouter (`OPENROUTER_API_KEY`) ou Ollama local como alternativa

## Como rodar

```powershell
pip install --require-hashes -r requirements.txt   # uma vez (.venv recomendado)
# edite .env e preencha OPENAI_API_KEY
python main.py --cli               # loop interativo; o primeiro boot prepara o índice
python main.py --port 8080         # servidor FastAPI
python main.py --cli --graph       # CLI com grafo via extração LLM
```

Cheques rápidos (quando autorizados; instale antes `pip install --require-hashes -r requirements-dev.txt`):

```powershell
Get-ChildItem main.py, src/*.py | ForEach-Object { python -m py_compile $_.FullName }
python -m pytest tests/ -q
```

## API

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/query` | `{"question": "..."}` → `{answer, sources, validation, ...}` |
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
`sources[]` (`file`, `score`, `page`, `excerpt`), `validation`/`citation_validation`
(`verified/total/unverified`), `numeric_citations[]`, `claim_evidence`, `calculations`, `usage`, `rag_type`, `rag_label`, `timeseries_chart?`. A validação numérica informa também `method` e `requires_review`.

## Configuração (`.env`)

| Variável | Padrão | Efeito |
|---|---|---|
| `RAG_LLM_PROVIDER` | `openai` | `openai` \| `openrouter` \| `ollama` (endpoint compatível via overrides) |
| `RAG_LLM_MODEL` / `RAG_INTERP_MODEL` / `RAG_POPUP_MODEL` | `gpt-5-chat-latest` / `gpt-5-mini` / `gpt-5-mini` | Síntese / interpretação-rerank / explicações de citação |
| `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `RAG_LLM_API_KEY`, `RAG_LLM_BASE_URL` | — | Chave do provedor ativo ou overrides explícitos, sem fallback automático |
| `RAG_EMBED_MODEL` / `RAG_CHUNK_SIZE` / `RAG_CHUNK_OVERLAP` | `BAAI/bge-m3` / `1024` / `200` | Vetorização local e chunking |
| `RAG_BGE_RERANK` / `RAG_LLM_RERANK` | `1` / `1` | Cross-encoder local / rerank por LLM |
| `RAG_INDEX_AUTO_DOWNLOAD` / `RAG_INDEX_READ_ONLY` | `0` / `0` | Baixa índice portátil do release / congela índice após 1º boot (`=1`) |
| `RAG_GRAPH_STRUCT` / `RAG_GRAPH_EMBED` / `RAG_USE_GRAPH` | `1` / `0` / — | Estrutura sem extração LLM / embedding do grafo / extração por LLM |
| `RAG_VISION` / `RAG_RAPTOR_ENABLE` / `RAG_INGEST_LLM_ENRICHMENT` | `0` | Flags experimentais/desligadas |

## Índice

- O primeiro boot (re)indexa `data/` → `chroma_db/` (`chroma.sqlite3`, `bm25_nodes.pkl` e `indexed_manifest.json`); tamanho e tempo dependem do corpus e da máquina.
- Boots seguintes detectam mudanças por mtime (`sync_standard_index`) e só reindexam o necessário.
- Os IDs dos nós consideram o conteúdo completo. A migração para esse formato altera o fingerprint do pipeline e exige reconstrução na próxima inicialização com sincronização habilitada (`RAG_INDEX_READ_ONLY=0`).
- Para congelar: `RAG_INDEX_READ_ONLY=1`. Para usar o artefato de release em vez de reindexar: `RAG_INDEX_AUTO_DOWNLOAD=1`.
- O download requer `RAG_INDEX_REPO=proprietario/repositorio`, `RAG_INDEX_TAG` (padrão `index-v1`) e `RAG_INDEX_ASSET` (padrão `graph-rag-index.tar.gz`). Não existe release remota presumida. O utilitário `scripts/index_artifact.py` exporta e instala o formato local com manifesto e SHA-256; exporte com o servidor parado. Use apenas artefatos confiáveis, pois o cache BM25 contém pickle. Downloads autenticados não são suportados pelo utilitário.
- `chroma_db/`, `graph_store/`, `__pycache__/` são gerados — não editar nem versionar.

## Desenvolvimento

- `--graph` funciona no CLI e no servidor; `RAG_USE_GRAPH=1` também ativa extração via LLM. Mudanças no modo do grafo invalidam seu cache na próxima inicialização.
- Gráficos são retornados junto ao resultado de cada consulta, sem estado compartilhado. O timeout HTTP abrange interpretação, busca, síntese e validação; chamadas síncronas já iniciadas em threads podem terminar em segundo plano após o cancelamento.
- A validação numérica exige correspondência contextual conservadora por ocorrência. A API retorna `claim_evidence`, `calculations` e `usage`; correspondências heurísticas não são prova semântica. Cálculos são executados em Python a partir de planos JSON limitados. Veja [Confiabilidade, carga e avaliação](docs/CONFIABILIDADE.md).

- Prompts/rerank: `src/query_interpreter.py` + `src/analysis_engine.py` (modelos sempre via factory, sem hard-code).
- Novo retriever: seguir o padrão `text/tables/timeseries_retriever.py`, registrar a fonte no `query_interpreter` e passar a `engine.answer`.
- Cálculos e evidências: `src/calculations.py`, `src/evidence.py` e `src/numerical_validator.py`. `safe_exec.py` é um utilitário legado, fora do fluxo atual de cálculos.
- Detalhes por módulo: ver [PYTHON.md](docs/PYTHON.md) e [AGENTS.md](AGENTS.md).

## Estado de verificação

As alterações atuais foram feitas sem executar testes, avaliações ou o servidor. A resolução dos locks não comprova compatibilidade do aplicativo. Os comandos acima são instruções para execução futura.

## Licença

MIT — ver `LICENSE`.
