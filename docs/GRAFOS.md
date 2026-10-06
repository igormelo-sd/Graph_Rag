# Grafos de conhecimento no Graph_Rag

O grafo conecta documentos, chunks, entidades e observações estatísticas candidatas com proveniência. Consulte [ONTOLOGIA.md](ONTOLOGIA.md) para conceitos, contratos e limites.

## Opções independentes

| Opção | Padrão | Comportamento |
|---|---|---|
| `RAG_GRAPH_STRUCT` | `1` | Relações documentais determinísticas |
| `--graph` / `RAG_USE_GRAPH=1` | desligado | Extração de relações e consulta de sinônimos por LLM |
| `RAG_GRAPH_EMBED` | `0` | Solicita embedding na construção do PropertyGraphIndex |
| `RAG_ONTOLOGY_DISCOVER` | `0` | Propostas de classes para revisão humana |
| `RAG_ONTOLOGY_ENABLE` | `1` | Observações e filtros, também fora do grafo |

Embedding e descoberta não ativam a extração de relações por LLM. Descoberta isolada pode inicializar o grafo. Com estrutura, extração, embedding e descoberta desligados, o grafo não é inicializado, mas o modelo de domínio pode atuar nos demais componentes.

## Estrutura e observações

`src/graph_indexing.py` insere chunks com IDs reais e texto recuperável. `CONTIDA_EM` liga chunk/página; `PERTENCE_A_DOC` liga página/documento. `NEXT_CHUNK` e `SAME_PAGE` conectam chunks narrativos adjacentes da mesma página, sem presumir ordem entre modalidades diferentes. Não se cria automaticamente vínculo tabela/imagem-explicação pela coincidência de número do chunk.

Observações mantêm valor literal, dimensões e proveniência. `SUSTENTADA_POR` aponta ao chunk de origem; dimensões únicas geram relações tipadas. A hierarquia territorial usa o cadastro explícito; campos ausentes ou ambíguos ficam para revisão.

A engine usa `GraphRetriever.retrieve_context` para percorrer arestas de contexto após recuperar texto, tabelas, séries e imagens. `REPRESENTADA_EM` liga tabela/chunk; `TEM_TITULO`, `TEM_NOTA` e `DESCRITA_EM` levam ao contexto literal. Notas têm prioridade, com até seis chunks adicionais e profundidade dois por padrão. A associação por geometria é candidata e fica para revisão. O método legado `retrieve_neighbors` mantém fallback BM25 narrativo. Detalhes: [ESTATISTICAS_GRAFO.md](ESTATISTICAS_GRAFO.md).

## Extração e consulta

`OntologyPathExtractor` processa nós narrativos e solicita até seis relações por chunk. Cada tripla precisa respeitar os tipos e apresentar citação literal com os nomes envolvidos. Auditorias registram aceitação/rejeição; relações aceitas continuam candidatas a revisão.

Quando a fonte `graph` é consultada, dimensões reconhecidas podem recuperar localmente os chunks associados a observações, sem chamada ao LLM. Com `--graph`, `LLMSynonymRetriever` também consulta caminhos (`max_keywords=10`, `path_depth=2`). Resultados passam por filtros de conflito explícito e deduplicação.

Uma busca local por entidades e aliases também percorre relações auditadas com proveniência do extrator, evitando depender somente da correspondência de nomes do retriever LLM. Caminhos são preservados mesmo quando o chunk já veio da busca híbrida.

Perguntas com vários períodos podem recuperar observações individuais de cada período. Perguntas por municípios/regiões e subsetores selecionam descendentes cadastrados e registram os caminhos da hierarquia; não há agregação automática. O cadastro é limitado e não representa todos os municípios ou setores.

As relações LLM preservam modalidade, período mencionado, origem e situação de revisão. Negações reconhecidas bloqueiam relações positivas; associação não é prova causal. `ontology.retrieval_paths` expõe caminhos, e `ontology.comparisons` representa a derivação dos cálculos por consulta, sem persistir resultados como fatos.

Não há `VectorContextRetriever` registrado nesta rota: solicitar embedding não acrescenta uma consulta vetorial dedicada. Observações inseridas depois da construção tampouco recebem garantia de vetorização. O alcance efetivo do embedding precisa de verificação antes de atribuir ganho ao segundo embedding de grafos.

## Persistência e avaliação

O grafo é salvo em `graph_store/graph_store.json`, ou `RAG_GRAPH_DIR`. Configuração, corpus e hash do modelo invalidam seu cache. Falhas de quota podem acionar construção local; erros de disco, dependências ou configuração não são necessariamente cobertos pelo fallback. A visualização, quando disponível, mostra até 300 relações.

O harness prepara híbrido, estrutural e grafo LLM, com variantes de desativação parcial da ontologia. Os modos estrutural e LLM consultam observações; somente LLM consulta sinônimos pelo modelo. Construção e consulta são contabilizadas separadamente. Gabaritos precisam de revisão; nenhuma avaliação foi executada. Veja [CONFIABILIDADE.md](CONFIABILIDADE.md).
