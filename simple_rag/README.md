# simple_rag: o mesmo RAG, sem grafo

Implementação sem nenhum módulo de grafo. Seu `src/` é o de [`graph_rag/src`](../graph_rag/src)
sem `graph_indexing`, `graph_retriever`, `graph_ontology`, `ontology_extractor`,
`relation_semantics` e `community_search`; `analysis_engine`, `startup`, `query_interpreter`,
`parent_context` e `domain_ontology` não têm ganchos de grafo, e todos os outros módulos são
idênticos aos do `graph_rag` (conferido por `tests_shared/test_implementations.py`). Assim, a
comparação entre as duas pastas mede o efeito de acrescentar o grafo.

Fluxo da comparação: **corpus → extração e trechos (mesmo preparo do GraphRAG) → embeddings →
busca vetorial + BM25 → fusão RRF → reranking → trechos pais → contexto → resposta com fontes**.
A ontologia de domínio (anotações e filtro de conflitos) vale nas duas versões. A diferença é que o
`simple_rag` preenche as vagas extras com os próximos trechos do ranking, e o `graph_rag` usa
candidatos do grafo. Detalhes e números: [comparacao/README.md](../comparacao/README.md).

Arquivos próprios desta pasta: `chunk.py` (trecho do índice), `vectors.py` (normalização e
cosseno), `index_store.py` (índice JSON atômico), `rag.py` (classe `SimpleRAG` e entrada dos comandos
`indexar`, `perguntar` e `comparar`, implementados em `cli.py`), `main.py` (aplicação completa),
`config/` (extensões de ontologia, cópia da do `graph_rag`) e `tests/`.

## Uso

Na raiz do repositório, com o `.env` e o ambiente descritos no [README](../README.md):

```powershell
# Prepara o corpus de ../data uma vez e grava o índice em simple_rag/indice e graph_rag/indice.
.\.venv\Scripts\python.exe simple_rag/rag.py indexar
.\.venv\Scripts\python.exe simple_rag/rag.py perguntar "Sua pergunta"

# Aplicação completa (índice Chroma próprio), como a do GraphRAG, sem --graph:
.\.venv\Scripts\python.exe simple_rag/main.py --cli
```

`simple_rag/main.py --graph` é recusado: não há grafo nesta pasta. Rode sempre uma
implementação por processo (`rag_app.bootstrap` rejeita módulos de outra origem).

## Testes

```powershell
.\.venv\Scripts\python.exe -m pytest simple_rag/tests -q
.\.venv\Scripts\python.exe scripts/test_all.py --suite simple_rag_src   # suíte do graph_rag contra simple_rag/src
```

Os testes usam modelos simulados e não medem qualidade das respostas.
