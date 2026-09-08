# RAGs/rag_principal — RAG Principal (híbrido)

> Leia primeiro `../AGENTS.md` (espelhamento do `src/`) e `../../AGENTS.md` (regras globais).

## Papel

Engine **padrão** do sistema: retrieval **híbrido** (Vector + BM25) sobre texto,
mais retrievers de **tabelas** e **séries temporais** via pandas e grafo de
conhecimento (opcional, `--graph`). Roda em **:8080** no Docker.

## Arquivos-chave

- `main.py` — entrypoint: servidor FastAPI (porta padrão 8000; compose usa 8080),
  `--cli` para loop interativo, `--graph` habilita o grafo. Monta `sys.path`
  (raiz + `src/` + `.agents/`).
- `src/startup.py` — `initialize(base_dir, data_dir=None, use_graph=False)`:
  1. LLMs via `llm` (`make_llm` + `require_api_key`; interp usa `RAG_INTERP_MODEL`)
  2. resolve `data/` (`index_manifest.resolve_data_dir`) e `chroma_db` (`resolve_db_dir`)
  3. baixa/valida o índice portátil (`ensure_principal_index`, `scripts.index_artifact`)
  4. `sync_standard_index` → detecta mudanças (mtime) e (re)indexa + BM25
  5. monta retrievers híbridos + `LLMRerank` + `DomainSkillRegistry` + `AnalysisEngine`
- `src/api.py` — FastAPI: `POST /query` (schema `{"question"}`), `GET /health`,
  `GET /app` (frontend estático). Chama `interpret_query` → `engine.answer` →
  `validate_numbers`.
- `src/query_interpreter.py` — `interpret_query(question, llm)` devolve
  `{sources, rewritten_query, is_labor_market}`. É onde o LLM decide fontes.
- `src/analysis_engine.py` — roda retrievers **em paralelo** e sintetiza a
  resposta final com o LLM (`self._llm.complete`; grafo opcional via `--graph`).
- `src/text_retriever.py` — `build_hybrid_retriever` (VectorIndex + BM25),
  `TextRetriever` com rerank.
- `src/tables_retriever.py` — extrai dados de tabelas (pandas) dos boletins.
- `src/timeseries_retriever.py` — extrai/análise de séries temporais (pandas).
- `src/numerical_validator.py` — `validate_numbers(answer, source_nodes)`;
  checa números citados contra as fontes (usa execução segura).
- `src/graph_indexing.py`, `src/graph_retriever.py` — grafo de conhecimento
  (habilitado via `--graph`; não ativo no compose por padrão).
- `src/processing.py` — `process_documents(docs)` → nós (`type=text|table`).
  ⚠️ já corrigido: precisa `import os` no topo (erro `NameError: os` histórico).
- `src/indexing.py` — `create_or_load_index`, `setup_embeddings` (bge-m3),
  `load_nodes_cache` (bm25_nodes.pkl).
- `src/ingestion.py` — `load_documents(data_dir)` — lê os PDFs.
- `src/labor_market_skill.py` — carrega `.agents/skills/labor_market_analysis`.
- `src/safe_exec.py` — execução segura para análise pandas.
- `src/logger.py` — `get_logger`/`setup_logging`.

## Mudanças comuns

- **Ajustar prompt/rerank:** `query_interpreter.py` (interpretação) e
  `analysis_engine.py` (síntese). Modelos vêm da factory — não hard-code.
- **Mudar retrieval:** `text/tables/timeseries_retriever.py` (shared files →
  aplique nas 4 variantes, exceto orquestrador).
- **Adicionar fonte nova:** siga o padrão dos retrievers + registre no
  `query_interpreter` (devolver a fonte) + passe ao `engine.answer`.

## Armadilhas / não alterar

- **`src/*` compartilhado** com agentic/raptor/selfrag (veja `RAGs/AGENTS.md`).
- **`chroma_db/`, `graph_store/`, `__pycache__/`** — gerados; não editar.
- `main.py` default é porta 8000, mas o **compose manda 8080** — não troque a
  porta no compose por engano.
- `SafeExec`/`numerical_validator` — altere com cuidado (segurança).

## Comandos

```powershell
python RAGs/rag_principal/main.py --cli                  # CLI local
python -m py_compile RAGs/rag_principal/src/*.py          # checa sintaxe
docker compose -f docker/docker-compose.yml logs -f rag-principal
```
