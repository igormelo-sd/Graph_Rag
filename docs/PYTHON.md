# PYTHON.md — Funcionalidades técnicas do projeto

> Documentação técnica do RAG Estatístico SP (engine principal/híbrida).
> Para a explicação acessível, ver [RAG](RAG.md), [GRAFOS](GRAFOS.md), [ONTOLOGIA](ONTOLOGIA.md)
> e `../COMO_FUNCIONA.md`. Para rodar, ver `../README.md`.

## 1. Stack e entrypoint

- **Linguagem/estilo**: Python 3.10+, tipagem parcial (`from __future__ import annotations`
  nos módulos novos), logging estruturado via `src/logger.py` (`setup_logging`/`get_logger`).
- **Entrypoint**: `main.py` — dois modos:
  - `python main.py --port 8080` → servidor FastAPI/uvicorn (`_run_server`).
  - `python main.py --cli [--graph]` → loop interativo (`_run_cli`): interpreta, responde,
    valida números e lista referências com score.
  - `sys.path` montado para raiz + `src/` + `.agents/`; stdout/stderr forçados para UTF-8.
- **Dependências centrais** (`requirements.txt`): `llama-index` (+ `embeddings-huggingface`,
  `llms-openai`, `vector-stores-chroma`, `retrievers-bm25`), `chromadb>=0.5`, `pandas`,
  `fastapi`/`uvicorn`, `sentence-transformers`, `rank_bm25`, `networkx`+`matplotlib` (grafo),
  `faiss-cpu` (opcional), `ragas`, `pypdf`/`pymupdf`/`camelot-py` (ingestão), `langchain-community==0.3.31`
  (pin documentado: evita quebra de import do `ragas`).

## 2. Camada de LLMs — factory única (`src/llm.py` + `.agents/llm_factory.py`)

Nenhum módulo instancia `OpenAI(api_key=...)` solto; tudo passa pela factory:

- **Provedores**: `maritaca` (padrão, `https://chat.maritaca.ai/api`), `openai`, `ollama`
  (local, `http://127.0.0.1:11434/v1`), OpenRouter via chaves — endpoints OpenAI-compatíveis.
- **Modelos por papel**: síntese (`RAG_LLM_MODEL`, ex. `sabia-4`), interpretação/rerank
  (`RAG_INTERP_MODEL`, ex. `sabiazinho-4`), explicações de citação (`RAG_POPUP_MODEL`).
  Modelos fora do catálogo LlamaIndex (ex. `sabia-4`) são registrados via `_register_model`.
- **Resiliência**: fallback entre chaves (`OPENAI_API_KEY → OPENAI_API_KEY_2 → MARITACA → OPENROUTER`),
  detecção de `429/credit_balance_exhausted` com troca automática, `require_api_key()` com
  mensagem de erro acionável, `llm_concurrency()` (Ollama = 1 por padrão).
- **Dois consumidores**: `make_llm()` → objeto LlamaIndex (sync); `openai_client_kwargs()` →
  kwargs para `OpenAI`/`AsyncOpenAI` crus.

## 3. Ingestão e chunking (`ingestion.py`, `processing.py`)

- `load_documents(data_dir)`: lê PDFs extraindo **texto, tabelas e gráficos** (OCR/visão),
  com metadados de proveniência (`source_file`, `page`).
- `process_documents(docs)` separa três caminhos:
  - **Texto** → `RecursiveCharacterTextSplitter` via `LangchainNodeParser`
    (`RAG_CHUNK_SIZE=1024`, `RAG_CHUNK_OVERLAP=200`) + `TitleExtractor`/`KeywordExtractor`
    (desligável via `RAG_INGEST_LLM_ENRICHMENT`, off por padrão no Ollama); seção detectada
    por heurística determinística (`_detect_section_title`).
  - **Tabela** → chunking determinístico em texto estruturado `Coluna: valor`: tabela
    pequena (≤ `RAG_SMALL_TABLE_MAX_ROWS=10`) = 1 chunk (`full_table`); grande = 1 chunk por
    linha (`row_per_chunk`); metadados inferidos sem rede (`_infer_table_metadata`: período,
    granularidade, indicadores) ou enriquecidos via LLM em paralelo (`ThreadPoolExecutor`).
  - **Imagem** → 1 nó por gráfico, sem splitter (`image_single`).
- Pós-processamento: `chunk_id`/`total_chunks_page` sequenciais por `(arquivo, página)` e
  ids determinísticos sha256 (`_assign_deterministic_ids`) → rebuilds idempotentes.

## 4. Embeddings e índice (`indexing.py`, `index_sync.py`, `index_manifest.py`)

- `setup_embeddings()`: `HuggingFaceEmbedding(BAAI/bge-m3)`, 1024 dim, normalizado, batch
  e device parametrizáveis (`RAG_EMBED_BATCH_SIZE`, `RAG_EMBED_DEVICE`, `RAG_EMBED_MAX_LENGTH=8192`).
  **Vetorização 100% local** — dado sensível não sai da máquina nessa etapa.
- `create_or_load_index()`: ChromaDB persistente, coleção `estatisticas` (cosseno), com
  **staging & swap transacional** (`estatisticas__staging` → rename) para evitar corrupção/WinError 32,
  validação de contagem + smoke query com o próprio modelo antes de promover, cache BM25
  (`bm25_nodes.pkl`, escrita atômica `.tmp` + `os.replace`) e FAISS opcional (`faiss_store.py`).
- `update_index_incrementally()`: insere substitutos **antes** de deletar ids antigos das fontes
  alteradas; mescla o cache BM25 só das fontes mudadas (`merge_nodes_cache`).
- `validate_embedding_compat()`: aborta o boot se modelo/dimensão do manifesto
  (`indexed_manifest.json`, `schema_version=2`) divergir do runtime.
- `resolve_data_dir`/`resolve_db_dir`: resolução de `data/` e `chroma_db` (local vs. container).
- Índice portátil: `ensure_principal_index` baixa release validado (`scripts/index_artifact`,
  `RAG_INDEX_AUTO_DOWNLOAD`); `RAG_INDEX_READ_ONLY=1` congela após o 1º boot.

## 5. Retrieval híbrido (`text_retriever.py` + retrievers especializados)

- `build_hybrid_retriever(index, bm25_nodes, node_type, llm)`: `VectorIndexRetriever`
  (top_k=`RAG_RETRIEVAL_TOP_K=80`, filtro por `type`) + `BM25Retriever` (português, stemmer)
  fundidos por `QueryFusionRetriever` (`reciprocal_rerank`, `num_queries=2`, prompt PT-BR que
  preserva setor/local/período/indicador). Sem nós BM25, cai para só-vetorial.
- Especializados: `TextRetriever` (filtra `type!=table`, sanitiza controle-chars, rerank com
  fallback para score), `TablesRetriever`/`TimeSeriesRetriever` (pandas: comparação entre anos,
  variações, payload de gráfico para a API), `ImagesRetriever`, `GraphRetriever` (ver [GRAFOS.md](GRAFOS.md)).
- Diversificação `_diversify_by_document`: máx. `RAG_MAX_CHUNKS_PER_DOCUMENT=3` por fonte, com
  cota de 25% para resumos RAPTOR quando existirem; limites `RAG_TEXT_TOP_N=20`,
  `RAG_STRUCTURED_TOP_N=10`, candidatos `RAG_RERANK_CANDIDATE_LIMIT=40`, final `RAG_RERANK_TOP_N=24`.

## 6. Rerank em 3 níveis (`startup.py`)

1. **Cross-encoder local** `BAAI/bge-reranker-v2-m3` (`SentenceTransformerRerank`, `RAG_BGE_RERANK=1`,
   padrão) — melhor custo/benefício em PT-BR, sem chamada de API.
2. **`LLMRerank`** (`choice_batch_size=30`) se `RAG_LLM_RERANK=1` e o BGE falhar/estiver off.
3. **`ScoreReranker`** determinístico (preserva ordem híbrida) — padrão no Ollama, onde lotes de
   candidatos estourariam janela/latência (`llm_reranking_enabled()`).

## 7. Orquestração da resposta (`query_interpreter.py`, `analysis_engine.py`, `query_service.py`)

- `interpret_query(question, llm)` → `{sources, rewritten_query, rewritten_queries?, is_labor_market}`:
  o LLM roteia por fonte (texto/tabelas/séries/imagem/grafo).
- `AnalysisEngine.answer(...)`: dispara retrievers **em paralelo** (`asyncio.to_thread` +
  `asyncio.gather` com timeout global `request_timeout_seconds()`), dedup por `node_id`,
  **costura do grafo** (`retrieve_neighbors`, +≤30%/6 vizinhos), síntese em **1 chamada LLM**
  com contexto unificado + bloco de skill de domínio; contexto vazio → `REFUSAL_TEXT`.
- `execute_engine_query(...)` (`query_service.py`): interpreta → executa (com `asyncio.wait_for`) →
  `sanitize_answer` (answer_policy) → `validate_numbers` + `validate_citations` →
  `generate_popup_explanations` → serializa `QueryResponse` + `QueryDiagnostics`
  (sources, chunks, verified/total, tokens e custo estimados).

## 8. Grafo + ontologia (opt-in, custo-zero por padrão)

- **Estrutural** (`RAG_GRAPH_STRUCT=1`): arestas determinísticas `CONTIDA_EM`, `PERTENCE_A_DOC`,
  `NEXT_CHUNK`, `SAME_PAGE`, `DESCRITA_EM` — costura de contexto sem nenhuma chamada LLM.
- **Semântico** (`--graph` / `RAG_GRAPH_EMBED=1`): `DynamicLLMPathExtractor` (máx. 6 triplas/chunk)
  sobre nós narrativos; entidades `Indicador/Setor/Região/Período/FonteDados/...`, relações
  `CRESCEU_EM/RECUOU_EM/PERTENCE_A/APLICA_SE_A/MEDIDO_POR/RELACIONA_COM`; persistência em
  `graph_store/graph_store.json` (+ PNG via networkx/matplotlib); fallback estrutural em falta de cota.
- **Ontologia** (`graph_ontology.py`, `RAG_ONTOLOGY_DISCOVER=0`): descobre até 4 tipos extras do
  corpus (amostra de 6 chunks, 1 chamada LLM, cache `ontology.json`).
- Detalhes: [GRAFOS.md](GRAFOS.md) e [ONTOLOGIA.md](ONTOLOGIA.md).

## 9. Validação e segurança de execução

- `numerical_validator.py::validate_numbers` — cada número da resposta é procurado nos nós-fonte;
  saída `{verified, total, unverified}` + `format_validation_report` (CLI).
- `citation_validator.py` + `popup_explanations.py` (modelo leve `RAG_POPUP_MODEL`) — citações
  `[n]` verificadas e explicadas.
- `safe_exec.py` — execução sandboxeada do pandas gerado (sem ela, código do LLM rodaria livre).
- `answer_policy.py::sanitize_answer` — higieniza a resposta antes de serializar.
- `structured_output.py` — contratos de saída; `provenance.py` — `source_file/page`, score de relevância.

## 10. API HTTP (`api.py`, `api_models.py`, `api_security.py`)

- `POST /query {"question"}` (validação: 1–4000 chars; `503` se engine não pronta; `504` em timeout)
  → `QueryResponse{answer, sources_used, rewritten_query, sources[SourceInfo], validation,
  citation_validation, numeric_citations[], rag_type, rag_label, timeseries_chart?}`.
- `GET /health` profundo (engine, Chroma count, BM25 nodes, embedding) com status
  `ok/degraded/starting`; `GET /metrics` (Prometheus); `/docs` (Swagger); `/` redireciona para
  `/app/` (frontend) se existir, senão `/docs`.
- Segurança opt-in sem dependências extras: `x-api-key` (`RAG_API_KEY`), rate limit deslizante
  por IP (`RAG_RATE_LIMIT=30/60s`, em memória — Redis se multirréplica), CORS explícito
  (default só origens locais), `SecurityHeadersMiddleware` (nosniff, DENY, CSP, etc.).

## 11. Observabilidade e custo

- `metrics.py`: middleware conta latência/erros por `(serviço, rota)` e estima tokens/custo
  (`estimate_tokens` em `runtime.py`, preços via `RAG_INPUT/OUTPUT_COST_PER_MILLION_USD`),
  exportado em `/metrics`.
- `usage_tracker.py`: acompanhamento de uso; logs com `extra={question, sources, latency_ms,
  verified, tokens, cost}` por requisição + `log.warning` dedicado a números não verificados.

## 12. Skills de domínio (`domain_skills.py`, `labor_market_skill.py`, `.agents/skills/`)

`DomainSkillRegistry(base_dir)` descobre skills em `.agents/skills/` (ex.:
`labor_market_analysis`) e injeta o bloco de prompt de domínio na síntese — é assim que o
redator "analisa como economista" sem hard-code de prompt na engine.

## 13. Testes (`tests/`, 15 suítes, `pytest`)

| Suíte | Cobre |
|---|---|
| `test_answer_policy`, `test_structured_output` | Higienização e contratos de resposta |
| `test_api_security`, `test_metrics` | Auth/rate-limit/headers, métricas Prometheus |
| `test_blockers`, `test_robustness`, `test_drift` | Travas, robustez, detecção de deriva |
| `test_domain_skills` | Registro de skills |
| `test_index_artifact` | Download/validação do índice portátil |
| `test_llm_config`, `test_text_retriever_config` | Config de provider e de retrieval |
| `test_popup_explanations`, `test_validators` | Explicações e validadores numérico/citação |
| `test_processing`, `test_safe_exec` | Chunking, execução sandboxeada |

## 14. Pontos de extensão (onde mexer)

- Novo retriever/fonte → padrão `text/tables/timeseries_retriever.py` + registrar em
  `query_interpreter` + passar a `engine.answer`.
- Trocar provider/modelo → só `.env` (+ `llm.py`/`.agents/llm_factory.py` se for provider novo).
- Ajustar qualidade → `RAG_CHUNK_*`, `RAG_RETRIEVAL_TOP_K`, `RAG_RERANK_*`, prompts de
  `query_interpreter.py`/`analysis_engine.py`.
- Nunca editar: `chroma_db/`, `graph_store/`, `__pycache__/` (gerados); `SafeExec` e validadores
  exigem revisão de segurança.
