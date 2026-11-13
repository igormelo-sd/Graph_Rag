# Graph_Rag — orientações do repositório

Leia também [.agents/AGENTS.md](.agents/AGENTS.md) ao alterar skills. Este é um repositório independente; não pressupõe variantes ou arquivos Docker em diretórios superiores.

## Arquitetura

- `graph_rag/`: RAG com grafo: `main.py`, `src/` (inclui os módulos de grafo), `tests/`, `config/` e `docs/` próprios. Ao alterar código dela, siga [graph_rag/AGENTS.md](graph_rag/AGENTS.md).
- `simple_rag/`: RAG sem grafo. Seu `src/` é o de `graph_rag/src` **sem** `graph_indexing`, `graph_retriever`, `graph_ontology`, `ontology_extractor`, `relation_semantics` e `community_search`, e com `analysis_engine`, `startup`, `query_interpreter`, `parent_context` e `domain_ontology` sem ganchos de grafo. Os demais módulos são idênticos byte a byte (`tests_shared/test_implementations.py`): ao mudar um módulo comum, altere as duas pastas.
- `data/`: corpus compartilhado pelas duas implementações. A raiz não tem código de RAG.
- `rag_app/`: infraestrutura comum. Importa módulos de `src/` pelo nome curto; `rag_app.bootstrap.activate` resolve esses nomes na pasta `src` da implementação ativada, e cada implementação roda em processo próprio.
- `comparacao/`: perfil, variantes (`simple_rag`, `parent_rag`, `graph_rag`) e avaliação experimental.
- `main.py` e `start.bat` da raiz são atalhos para `graph_rag/main.py` e `graph_rag/start.bat`; `simple_rag/main.py` é a entrada da versão sem grafo.

A antiga aplicação principal (`src/` e `tests/` da raiz) foi removida; o último estado com ela está na tag `tcc-congelamento`.

## Convenções

Preserve alterações locais existentes. Use a factory do aplicativo para chamadas LLM. Ao alterar o contrato da resposta, mantenha API e documentação alinhadas. Nas skills de domínio, preserve os marcadores `rag-context` e as seções consumidas pelo código: esse conteúdo pode ser injetado na síntese em produção.

Não edite manualmente `chroma_db/`, `graph_store/` ou `__pycache__/`. Mudanças de processamento exigem atenção ao fingerprint do pipeline e à compatibilidade do manifesto.

Os resultados do TCC de 04/11/2026 estão congelados e descrevem a organização anterior (`rag_simples`, `graphrag`, corpus em `graphrag/data`); o registro e a tag `tcc-congelamento-20261104` os preservam e não devem ser reescritos. A organização atual (v4) é um experimento novo: qualquer mudança em `comparacao/`, nas duas pastas `src`, em `comparacao/config.json` ou nas perguntas exige novo preparo e novo registro de congelamento antes de rodadas finais. Veja [comparacao/README.md](comparacao/README.md).

## Dependências e execução

As entradas editáveis são `requirements.in` e `requirements-dev.in`. Os locks `.txt` têm hashes e alvo Windows x64/Python 3.13; `scripts/lock_dependencies.ps1` permite regenerá-los deliberadamente. Consulte [README.md](README.md) para instalação e execução.

Respeite instruções explícitas de não executar testes, servidor, avaliações ou validadores. A presença de uma suíte não demonstra que ela passou. Execute cada suíte em processo separado com `scripts/test_all.py` (inclui `simple_rag_src`, que roda os testes de `graph_rag/tests` contra `simple_rag/src`).
