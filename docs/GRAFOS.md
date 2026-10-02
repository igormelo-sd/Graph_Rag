# Grafos de conhecimento no Graph_Rag

Um grafo representa entidades ligadas por relações. Por exemplo, `Emprego → APLICA_SE_A → Interior` é uma ilustração de relação, não um dado extraído ou comprovado. Veja [RAG](RAG.md) e [Ontologia](ONTOLOGIA.md).

## Três configurações distintas

| Configuração | Padrão | Comportamento |
|---|---|---|
| `RAG_GRAPH_STRUCT` | `1` | Injeta relações documentais determinísticas |
| `--graph` / `RAG_USE_GRAPH=1` | desligado | Ativa extração de relações via LLM |
| `RAG_GRAPH_EMBED` | `0` | Habilita vetorização dos nós do grafo |
| `RAG_ONTOLOGY_DISCOVER` | `0` | Propõe até quatro tipos adicionais quando o grafo é inicializado |

Embedding do grafo e extração por LLM são opções distintas. `--graph` funciona tanto no CLI quanto no servidor. Desativar todas as opções de grafo impede sua inicialização; habilitar descoberta de ontologia isoladamente não cria um grafo.

## Estrutura dos documentos

`src/graph_indexing.py` injeta `CONTIDA_EM` (chunk/página), `PERTENCE_A_DOC` (página/documento), `NEXT_CHUNK`, `SAME_PAGE` e `DESCRITA_EM` (tabela ou imagem/texto próximo). Construir essas relações não usa LLM, mas consome recursos da máquina.

A costura em `GraphRetriever.retrieve_neighbors` usa o cache BM25: encontra chunks com mesmo arquivo e página e `chunk_id` anterior ou posterior. A engine deduplica e anexa até seis vizinhos, sem calcular uma cota de 30%. Essa rotina não percorre `NEXT_CHUNK`, `SAME_PAGE` ou `DESCRITA_EM` armazenadas no grafo. Portanto, não há uma etapa dedicada que garanta recuperar a explicação de cada tabela pela aresta `DESCRITA_EM`.

Exemplo hipotético: a busca recupera uma frase incompleta e o chunk anterior contém seu sujeito. Anexar esse vizinho pode melhorar o contexto; o benefício depende dos metadados e deve ser avaliado.

## Relações extraídas por LLM

`DynamicLLMPathExtractor` processa nós narrativos, solicitando até seis triplas por chunk. Os tipos sugeridos pela ontologia incluem indicador, setor, região, período e fonte; relações incluem `CRESCEU_EM`, `RECUOU_EM`, `PERTENCE_A`, `APLICA_SE_A`, `MEDIDO_POR` e `RELACIONA_COM`. Triplas geradas são interpretações do modelo e precisam de auditoria.

O grafo é persistido normalmente em `graph_store/graph_store.json`, com visualização quando disponível. Configuração e mudanças no corpus podem invalidar o cache. Erros de extração têm fallback estrutural; isso não garante operação livre de falhas de disco, dependências ou configuração.

## Consulta direta

Quando a consulta inclui a fonte `graph`, `LLMSynonymRetriever` gera termos com LLM (`max_keywords=10`) e consulta caminhos (`path_depth=2`), incluindo texto dos nós. Essa chamada pode consumir API mesmo num grafo somente estrutural. A consulta direta é diferente da costura por metadados e seus resultados são deduplicados junto às demais fontes.

## Avaliação pendente

O grafo pode ampliar contexto e conectar entidades; não há resultado experimental atual demonstrando ganho de qualidade. O roteiro em `scripts/evaluate_retrieval.py` separa híbrido, estrutural e grafo LLM. É necessário revisar o gabarito e contabilizar construção, consulta e cache separadamente. Veja [CONFIABILIDADE.md](CONFIABILIDADE.md). Nenhuma avaliação foi executada nesta atualização.
