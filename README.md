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
| Bootstrap | `src/startup.py:initialize` | LLMs → resolve `data/`/`chroma_db` → índice portátil → `sync_standard_index` → retrievers + reranker + skills + engine |
| Interpretação | `src/query_interpreter.py` | LLM decide `sources`, `rewritten_query`, `is_labor_market` |
| Síntese | `src/analysis_engine.py` | Roda retrievers em paralelo, sintetiza com o LLM |
| Texto | `src/text_retriever.py` | Híbrido VectorIndex + BM25 + rerank |
| Tabelas / séries | `src/tables_retriever.py`, `src/timeseries_retriever.py` | Extração/análise pandas dos boletins |
| Imagens | `src/images_retriever.py` | Nós `type=image` |
| Grafo | `src/graph_indexing.py`, `src/graph_retriever.py` | Estrutural por padrão (`RAG_GRAPH_STRUCT=1`); embedding com `RAG_GRAPH_EMBED=1`; extração LLM com `--graph` |
| Validação | `src/numerical_validator.py`, `src/citation_validator.py` | Confere números/citações contra os nós-fonte (execução segura em `src/safe_exec.py`) |
| API | `src/api.py` | FastAPI + lifespan; segurança (`src/api_security.py`), modelos (`src/api_models.py`), métricas (`src/metrics.py`) |
| LLMs | `src/llm.py` (+ `.agents/llm_factory.py`) | Factory única; Maritaca padrão, OpenAI/Ollama/OpenRouter configuráveis — sem `OpenAI(api_key=...)` solto |
| Ingestão | `src/ingestion.py`, `src/processing.py`, `src/indexing.py`, `src/index_sync.py`, `src/index_manifest.py` | PDFs → nós (`text|table|image`) → Chroma + `bm25_nodes.pkl` + manifesto |
| Skills | `src/domain_skills.py`, `src/labor_market_skill.py`, `.agents/skills/` | Skills de domínio (ex.: mercado de trabalho) |

Embeddings 100% locais: `BAAI/bge-m3` (1024 dim) via `src/indexing.py:setup_embeddings`.
Rerank padrão: cross-encoder local `BAAI/bge-reranker-v2-m3` (`RAG_BGE_RERANK=1`), com fallback para `LLMRerank` ou `ScoreReranker`.

## Estrutura

```
main.py  requirements.txt  .env  LICENSE
src/            # 36 módulos (api, engine, retrievers, indexação, validação)
.agents/        # llm_factory.py + skills/
data/           # 10 PDFs Seade (fonte indexada)
chroma_db/      # gerado no 1º boot: chroma.sqlite3 + bm25_nodes.pkl + indexed_manifest.json
tests/          # 15 suítes pytest
```

## Pré-requisitos

- Python 3.10+ (.venv recomendado), ~4 GB livres (modelo bge-m3 + Chroma)
- Chave de LLM no `.env` — padrão Maritaca (`MARITACA_API_KEY`); OpenAI/OpenRouter/Ollama como alternativa

## Como rodar

```powershell
pip install -r requirements.txt   # uma vez (.venv recomendado)
# edite .env e preencha MARITACA_API_KEY
python main.py --cli               # loop interativo (1º boot: ~20-30 min em CPU, bge-m3)
python main.py --port 8080         # servidor FastAPI
python main.py --cli --graph       # CLI com grafo via extração LLM
```

Cheques rápidos:

```powershell
python -m py_compile main.py src\*.py
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
(`verified/total/unverified`), `numeric_citations[]`, `rag_type`, `rag_label`, `timeseries_chart?`.

## Configuração (`.env`)

| Variável | Padrão | Efeito |
|---|---|---|
| `RAG_LLM_PROVIDER` | `maritaca` | `maritaca` \| `openai` \| `ollama` (OpenRouter via chaves) |
| `RAG_LLM_MODEL` / `RAG_INTERP_MODEL` / `RAG_POPUP_MODEL` | `sabia-4` / `sabia-4` / `sabiazinho-4` | Síntese / interpretação-rerank / explicações de citação |
| `MARITACA_API_KEY`, `OPENAI_API_KEY`, `OPENAI_API_KEY_2`, `OPENROUTER_API_KEY` | — | Chaves com fallback automático |
| `RAG_EMBED_MODEL` / `RAG_CHUNK_SIZE` / `RAG_CHUNK_OVERLAP` | `BAAI/bge-m3` / `1024` / `200` | Vetorização local e chunking |
| `RAG_BGE_RERANK` / `RAG_LLM_RERANK` | `1` / `1` | Cross-encoder local / rerank por LLM |
| `RAG_INDEX_AUTO_DOWNLOAD` / `RAG_INDEX_READ_ONLY` | `0` / `0` | Baixa índice portátil do release / congela índice após 1º boot (`=1`) |
| `RAG_GRAPH_STRUCT` / `RAG_GRAPH_EMBED` / `RAG_USE_GRAPH` | `1` / `0` / — | Grafo determinístico custo zero / 2º embedding / força grafo |
| `RAG_VISION` / `RAG_RAPTOR_ENABLE` / `RAG_INGEST_LLM_ENRICHMENT` | `0` | Flags experimentais/desligadas |

## Índice

- O primeiro boot (re)indexa `data/` → `chroma_db/` (`chroma.sqlite3` ~31 MB / ~1490 nós + `bm25_nodes.pkl` + `indexed_manifest.json`).
- Boots seguintes detectam mudanças por mtime (`sync_standard_index`) e só reindexam o necessário.
- Para congelar: `RAG_INDEX_READ_ONLY=1`. Para usar o artefato de release em vez de reindexar: `RAG_INDEX_AUTO_DOWNLOAD=1`.
- `chroma_db/`, `graph_store/`, `__pycache__/` são gerados — não editar nem versionar.

## Desenvolvimento

- Prompts/rerank: `src/query_interpreter.py` + `src/analysis_engine.py` (modelos sempre via factory, sem hard-code).
- Novo retriever: seguir o padrão `text/tables/timeseries_retriever.py`, registrar a fonte no `query_interpreter` e passar a `engine.answer`.
- Segurança: `src/safe_exec.py` e `src/numerical_validator.py` — alterar com cuidado.
- Detalhes por módulo: ver `AGENTS.md` (espelho da árvore `src/`).

## Licença

MIT — ver `LICENSE`.
