# Funcionalidades técnicas do Graph_Rag

Veja [RAG](RAG.md), [Grafos](GRAFOS.md), [Ontologia](ONTOLOGIA.md) e [Como funciona](../COMO_FUNCIONA.md) para explicações didáticas; [README](../README.md) para execução.

## Ambiente e entrada

O alvo dos locks é Windows x64/Python 3.11. `requirements.in` e `requirements-dev.in` são as entradas; os respectivos `.txt` incluem versões transitivas e hashes. `scripts/lock_dependencies.ps1` regenera os locks. Bibliotecas resolvidas não significam compatibilidade testada.

`main.py --cli` inicia o modo interativo; `main.py --port 8080` inicia FastAPI. `--graph` funciona em ambos. A stack inclui LlamaIndex, Chroma, pandas, FastAPI e sentence-transformers; as versões exatas estão nos locks.

## Provedor e chamadas LLM

`src/llm.py` seleciona um provedor: `openai` (padrão), `openrouter` ou `ollama`. Os modelos de síntese, interpretação e popups podem ser configurados separadamente. `RAG_LLM_BASE_URL` e `RAG_LLM_API_KEY` permitem endpoint compatível personalizado. Não há fallback automático entre chaves ou provedores no aplicativo.

`make_llm()` fornece o cliente LlamaIndex instrumentado; `openai_client_kwargs()` fornece configuração para clientes compatíveis. `.agents/llm_factory.py` é um helper legado separado, não a factory do fluxo principal. As chamadas instrumentadas passam pelo controle de recursos e coletor de uso por consulta.

## Ingestão e índice

`ingestion.py` extrai texto, tabelas e imagens com proveniência. OCR, visão e enriquecimento dependem de configuração e ferramentas disponíveis; não se deve presumir leitura confiável de toda imagem. `processing.py` divide texto, estrutura tabelas e atribui IDs determinísticos baseados no conteúdo completo e na ocorrência.

`indexing.py` usa embeddings locais, por padrão `BAAI/bge-m3` com 1024 dimensões. Isso mantém a vetorização local; trechos enviados a um LLM remoto continuam saindo da máquina.

A reconstrução cria uma coleção de staging, verifica-a e promove-a em etapas: exclui a coleção anterior e renomeia a nova. Essa promoção não é uma transação atômica. O cache `bm25_nodes.pkl` é substituído por `os.replace`; Chroma, BM25 e manifesto não compõem uma única transação.

`index_sync.py` identifica fontes alteradas e atualiza o índice preservando IDs ainda presentes. Modelo, dimensão e fingerprint do pipeline são registrados no manifesto. IDs de conteúdo completo exigem reconstrução do índice antigo na próxima sincronização habilitada.

O índice portátil é opcional (`RAG_INDEX_AUTO_DOWNLOAD=0` por padrão), exige repositório explícito e inclui manifesto SHA-256. `scripts/index_artifact.py` exporta/instala esse formato; use artefatos confiáveis, pois BM25 contém pickle. `RAG_INDEX_READ_ONLY=1` evita sincronização depois da preparação inicial.

## Recuperação e rerank

`text_retriever.py` combina busca vetorial e BM25 por reciprocal rank fusion. `num_queries=2` conta a consulta original e uma alternativa. A preferência de três chunks por documento pode ser ultrapassada ao completar o limite final; não é um teto rígido.

O rerank tenta o cross-encoder local BGE por padrão, inclusive com Ollama. Quando ele está desativado ou falha, usa LLM se habilitado; caso contrário, preserva scores. O rerank LLM é desativado por padrão para Ollama.

Tabelas e séries recuperam células e pedem planos JSON. `calculations.py` calcula diferença, variação percentual, pontos percentuais, soma ou média usando Decimal, com referências e unidades verificadas. Nenhum Python gerado pelo LLM é executado nesse fluxo. `safe_exec.py` permanece como utilitário legado.

## Orquestração, grafo e skills

`query_interpreter.py` escolhe fontes e reescrita, ou retorna pedido de esclarecimento territorial sem LLM. `analysis_engine.py` recupera fontes em paralelo e percorre arestas de contexto por `GraphRetriever.retrieve_context`, acrescentando até seis chunks e priorizando notas/títulos. Não expande páginas inteiras. `knowledge_analytics.py` mantém a análise do corpus por processo e retorna relatórios isolados por chamada.

`--graph` ou `RAG_USE_GRAPH=1` ativa extração por LLM; `RAG_GRAPH_EMBED=1` habilita embedding dos nós do grafo, sem equivaler à extração. Observações são consultadas localmente por dimensões; `LLMSynonymRetriever` é usado somente com a opção de grafo LLM. Não há uma rota vetorial dedicada para o grafo. Consulte [GRAFOS.md](GRAFOS.md).

`DomainSkillRegistry` lê as configurações `rag-routing.json` e injeta somente o bloco entre marcadores `rag-context` do `SKILL.md` correspondente. Scripts e referências auxiliares não são executados automaticamente.

## Resposta, evidências e carga

`query_service.py` interpreta, executa, higieniza e valida. O contexto identifica fontes como `[Fonte: arquivo, p./aba ...]`; o prompt não exige citações inline salvo pedido. `citation_validator.py` verifica citações explícitas no formato `(Fonte: arquivo, p. X)`, não referências numéricas `[1]`.

`numerical_validator.py` verifica cada ocorrência de número com contexto de indicador, período, região e unidade. `verified` é uma correspondência heurística. `claim_evidence` fornece candidatos documentais; `calculations` distingue correção aritmética de revisão semântica; `usage` registra tokens disponíveis. Custo ausente é `null`, não zero.

`POST /query` retorna resposta, fontes, validação, evidências, cálculos, uso, gráfico opcional, `ontology` (dimensões, observações, auditorias, caminhos e grafo de derivação), `knowledge` e `clarification`. `GET /knowledge?question=...` consulta cobertura/divergências sem LLM. `domain_ontology.py` compartilha conceitos; `ontology_extractor.py` valida relações e `relation_semantics.py` preserva qualificadores. `/health`, `/metrics` e `/docs` expõem estado, métricas e contrato. Autenticação, rate limit e CORS dependem de configuração. Sobrecarga pode retornar 503 com `Retry-After`; timeout não interrompe necessariamente trabalho já iniciado em uma thread.

## Avaliação e estado de verificação

`scripts/evaluate_retrieval.py` prepara seis modos: híbrido, estrutural e grafo LLM, cada um com ativação ou desativação parcial da ontologia, com fontes base comuns e processos separados. Registra recall documental, correspondência textual de fragmentos, latência, erros e custo disponível; inicialização é contabilizada separadamente. Fragment-match não mede correção semântica.

`evaluation/cases.example.jsonl` contém rascunhos; o gabarito precisa ser conferido nos PDFs. As suítes em `tests/` incluem contratos, configuração, processamento, validadores e cálculos. Nenhum teste, avaliação ou servidor foi executado durante estas alterações.

Para parâmetros completos e limites, veja [CONFIABILIDADE.md](CONFIABILIDADE.md).
