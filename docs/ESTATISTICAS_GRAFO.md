# Observações, contexto e auditoria dos grafos

Esta evolução implementa os três aprimoramentos e os cinco usos adicionais discutidos. Não houve execução de testes, compilação, avaliação, ingestão ou servidor. Os exemplos são ilustrativos, não resultados observados no corpus.

## 1. Observações por célula

`processing.py` preserva a estrutura literal da tabela no metadado `table_structure`: colunas, linhas, posição original, identificador estável, título e notas. Cabeçalhos genéricos de Camelot podem ser substituídos pela primeira linha literal; cabeçalhos vazios ou duplicados não são convertidos para dicionários que perderiam células. Nesses casos, mantém-se o texto original para recuperação e revisão.

`statistical_observations.py` associa cada valor ao próprio cabeçalho e aos rótulos da linha. Por exemplo:

| Indicador | 2022 | 2023 |
|---|---|---|
| Taxa de desocupação (%) | 8,2 | 7,9 |

Com título literal indicando Estado de São Paulo, cada célula gera um candidato com seu ano, unidade e território. Os valores não recebem a combinação dos dois anos. Notas podem fornecer cobertura, base e fonte institucional. Metadados descritivos produzidos pelo LLM não completam essas dimensões.

Datas explicitamente rotuladas como publicação, edição ou divulgação ficam em `publication_periods`, separadas do período estatístico. A proveniência mantém ID do chunk, arquivo, página, posição no texto, tabela, linha, coluna, cabeçalho, rótulos, título e notas. Ausências e ambiguidades exigem revisão; resumos RAPTOR não geram novas observações.

Períodos distinguem ano, trimestre, mês e dia; meses abreviados e formatos numéricos reconhecidos são normalizados. Mês e trimestre não são considerados compatíveis apenas porque seus identificadores têm o mesmo tamanho. Partes de datas numéricas não geram valores observados.

## 2. Contexto recuperado pelas arestas

Tabelas têm entidades próprias e arestas `REPRESENTADA_EM` para os chunks. `TEM_TITULO` e `TEM_NOTA` conectam conteúdos literais encontrados na mesma página. `DESCRITA_EM` usa referência explícita como “Tabela 1”, também na mesma página. Para PDFs, a localização da caixa de Camelot ajuda a selecionar títulos numerados acima e notas abaixo; essa associação geométrica é candidata e permanece marcada para revisão.

A engine chama `GraphRetriever.retrieve_context` depois de reunir os resultados. A travessia prioriza notas, títulos e explicações, também considera `NEXT_CHUNK`/`SAME_PAGE` e acrescenta até seis chunks por padrão. A profundidade padrão é dois, com orçamento de 160 arestas examinadas. Os caminhos ficam em `ontology.retrieval_paths`.

- `RAG_GRAPH_CONTEXT_LIMIT`: padrão 6, faixa 1–30; a engine atualmente solicita no máximo 6.
- `RAG_GRAPH_CONTEXT_DEPTH`: padrão 2, faixa 1–3.

Não há vínculo por coincidência de ordinal entre tabela e texto, nem expansão de uma página inteira. O método legado `retrieve_neighbors` tenta primeiro as arestas e mantém fallback BM25 apenas para narrativa. A rota atual da engine usa a travessia diretamente.

## 3. Relações com qualificadores

`relation_semantics.py` rejeita relações positivas quando o trecho contém negação reconhecida. `ASSOCIADO_A` exige marcador de associação; `CAUSA` exige marcador causal literal e não aceita associação como prova causal. Crescimento e recuo precisam de marcadores correspondentes.

As relações preservam citação, modalidade (afirmação, incerteza ou condição), períodos mencionados, arquivo, página, chunk, método e situação de revisão. Não se atribui confiança numérica inventada. Uma alegação causal literal continua sendo uma interpretação candidata da fonte, sem demonstrar causalidade científica.

Auditorias incluem as relações aceitas com qualificadores e os candidatos rejeitados com motivos. Os controles por padrões são conservadores e podem rejeitar afirmações legítimas, especialmente trechos com várias orações.

## Usos adicionais

| Uso | Implementação e limite |
|---|---|
| Comparações rastreáveis | `ontology.comparisons` contém o grafo da consulta: comparação, operandos, base/final ou componentes, observações candidatas, fórmula e chunks de apoio. Não é persistido como fato do corpus. |
| Divergências | Valores distintos com indicador, território, período, unidade e natureza únicos e demais recortes reconhecidos iguais são sinalizados. Fontes diferentes podem participar; diferenças de escala/base/cobertura não são confundidas. Não se escolhe automaticamente uma versão. |
| Ambiguidades | Perguntas sobre indicador com “São Paulo” sem qualificação retornam `clarification.required=true` e opções territoriais, sem síntese pelo LLM. A disponibilidade indica candidatos indexados, não garantia de resposta; envie uma nova pergunta com o recorte explícito. |
| Hierarquias | Perguntas por municípios/regiões ou subsetores percorrem os descendentes cadastrados. O cadastro territorial atual é limitado; a hierarquia setorial inclui indústria de transformação e extrativa sob indústria. Não há soma automática. |
| Cobertura | `knowledge` descreve dimensões, combinações disponíveis, contagens e combinações solicitadas ausentes no índice. Ausência de candidato não prova inexistência do dado nos documentos ou na realidade. |

## API e avaliação futura

`POST /query` acrescenta `clarification` e `knowledge`, além dos novos campos de `ontology`. `GET /knowledge` retorna cobertura e divergências do corpus indexado sem LLM; `question` opcional restringe o relatório. O endpoint utiliza a autenticação, limite de requisições, fila e timeout do aplicativo.

O relatório limita combinações disponíveis a 200, lacunas solicitadas a 100 e grupos de divergência a 100. Alternativas e proveniências também são limitadas; as contagens e campos de truncamento indicam o recorte. Divergências são propostas para revisão de extração, revisão estatística e metodologia; dimensões desconhecidas não viram fatos conhecidos.

Foram preparados `tests/test_statistical_graph.py`, `tests/test_graph_paths.py` e casos adicionais de cálculo/processamento. O harness registra pedidos de esclarecimento, caminhos e divergências candidatas; suas contagens não medem acurácia. Todos permanecem sem execução.

O modelo passou a `economic-observations-v2`. A próxima preparação autorizada precisa de índices compatíveis; extensões externas revisadas precisam declarar essa versão. Caches e índices gerados não foram alterados manualmente.
