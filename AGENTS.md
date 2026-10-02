# Graph_Rag — orientações do repositório

Leia também [.agents/AGENTS.md](.agents/AGENTS.md) ao alterar skills. Este é um repositório independente; não pressupõe variantes ou arquivos Docker em diretórios superiores.

## Arquitetura

- `main.py`: CLI (`--cli`) e API (`--port 8080`); `--graph` ativa extração de relações via LLM nos dois modos.
- `src/startup.py`: resolve caminhos, prepara o índice e monta retrievers, reranker, skills e engine.
- `src/llm.py`: configuração do provedor ativo e factory usada pelo aplicativo. Não há troca automática de provedores após erro de crédito ou 429.
- `src/ingestion.py`, `processing.py`, `indexing.py`, `index_sync.py`, `index_manifest.py`: extração, nós determinísticos, índice e sincronização incremental.
- `src/text_retriever.py`: busca híbrida e diversificação; tabelas, séries e imagens têm retrievers próprios.
- `src/calculations.py`: operações limitadas em Decimal a partir de planos JSON. O fluxo atual não executa Python gerado pelo LLM; `safe_exec.py` permanece como utilitário legado.
- `src/graph_indexing.py`, `graph_retriever.py`, `graph_ontology.py`: grafo estrutural, extração opcional de relações e descoberta opcional de tipos.
- `src/analysis_engine.py`, `query_service.py`: recuperação, síntese e resultado por consulta, sem compartilhar gráfico entre respostas.
- `src/evidence.py`, `numerical_validator.py`, `citation_validator.py`: evidências e verificações heurísticas; não tratá-las como prova de correção semântica.
- `src/load_control.py`, `query_usage.py`: limites por processo e uso reportado pelo provedor.
- `src/api.py`, `api_models.py`, `api_security.py`, `metrics.py`: HTTP, contratos, segurança e observabilidade.

## Convenções

Preserve alterações locais existentes. Use a factory do aplicativo para chamadas LLM. Ao alterar o contrato da resposta, mantenha API e documentação alinhadas. Nas skills de domínio, preserve os marcadores `rag-context` e as seções consumidas pelo código: esse conteúdo pode ser injetado na síntese em produção.

Não edite manualmente `chroma_db/`, `graph_store/` ou `__pycache__/`. Mudanças de processamento exigem atenção ao fingerprint do pipeline e à compatibilidade do manifesto. A promoção da coleção Chroma ocorre em etapas; não é uma transação atômica conjunta com o cache BM25.

## Dependências e execução

As entradas editáveis são `requirements.in` e `requirements-dev.in`. Os locks `.txt` têm hashes e alvo Windows x64/Python 3.11; `scripts/lock_dependencies.ps1` permite regenerá-los deliberadamente. Consulte [README.md](README.md) para instalação e execução.

Respeite instruções explícitas de não executar testes, servidor, avaliações ou validadores. A presença de uma suíte não demonstra que ela passou. O roteiro de avaliação em `scripts/evaluate_retrieval.py` exige gabaritos revisados; exemplos em `evaluation/` não são resultados experimentais.

Veja [docs/CONFIABILIDADE.md](docs/CONFIABILIDADE.md) para limites de validação, cálculos, carga, custo e avaliação.
