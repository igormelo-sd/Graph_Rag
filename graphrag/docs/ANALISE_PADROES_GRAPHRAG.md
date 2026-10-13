# Ideias do GraphRAG Pattern Catalog para esta implementação

Atualização: as três prioridades desta análise receberam implementação inicial.
O diagnóstico abaixo registra o estado anterior às mudanças. Consulte
[padrões implementados](PADROES_IMPLEMENTADOS.md) para o comportamento atual.

Análise em 8 de outubro de 2026, baseada na leitura do site e do código local em
`Graph_Rag/graphrag`. Não foram executados servidor, indexação ou experimentos.
Os benefícios descritos abaixo são hipóteses a avaliar.

## Enquadramento

O [catálogo introdutório](https://graphrag.com/concepts/intro-to-graphrag/),
mantido pela Neo4j, apresenta GraphRAG como uma família de padrões de recuperação
que usam grafos. Cada padrão exige uma estrutura apropriada. Portanto, a aplicação
pode incorporar ideias do catálogo mantendo LlamaIndex e seu armazenamento atual;
uma migração para Neo4j seria uma decisão separada.

## Comparação com o código

| Padrão | Situação encontrada | Inspiração para o projeto |
|---|---|---|
| Busca vetorial expandida pelo grafo | `analysis_engine.py` combina resultados dos retrievers e chama `GraphRetriever.retrieve_context`. Essa expansão prioriza notas, títulos, representações e adjacência documental. Há também busca de relações e observações por pergunta. | Usar os trechos recuperados como pontos de partida para percorrer entidades compartilhadas e recuperar evidências em outros documentos. |
| Recuperação de filho e pai | Há ligações entre documento, página e trechos em `graph_indexing.py`, além de recuperação de vizinhos. Isso não equivale a indexar filhos pequenos e recuperar seus pais textuais. | Criar seções ou blocos maiores como pais, indexar filhos menores e devolver o pai quando um filho corresponder à pergunta. |
| Filtragem por metadados | `domain_ontology.filter_candidates` remove conflitos explícitos após a recuperação; mantém dados incompletos. O grafo também possui índices de dimensões nas observações. | Levar restrições confirmadas de período, território e indicador para a seleção inicial de candidatos; conservar uma saída explícita para metadados desconhecidos. |
| Resumos globais de comunidades | Não foi encontrada implementação de detecção de comunidades do grafo e síntese global de seus resumos. Existem referências a RAPTOR, que não demonstram esse fluxo. | Acrescentar comunidades, resumos com proveniência e um modo global de resposta. |
| Consultas por modelos predefinidos | Já existem travessias locais controladas para relações, observações e hierarquias; o armazenamento é `SimplePropertyGraphStore`, sem executor Cypher encontrado. | Organizar essas travessias em operações com parâmetros tipados, como indicador/região/período e relações de um setor. |

Fontes dos padrões: [busca vetorial com grafo](https://graphrag.com/reference/graphrag/graph-enhanced-vector-search/),
[filho e pai](https://graphrag.com/reference/graphrag/parent-child-retriever/),
[metadados](https://graphrag.com/reference/graphrag/metadata-filtering/),
[comunidades](https://graphrag.com/reference/graphrag/global-community-summary-retriever/) e
[consultas predefinidas](https://graphrag.com/reference/graphrag/cypher-templates/).

## Ordem sugerida

1. **Expandir pelos vínculos entre entidades.** Complementar a expansão documental
   com um percurso curto entre trecho, entidade e evidência relacionada. Preservar
   fonte e caminho, respeitar período e território e limitar o contexto retornado.
2. **Introduzir filhos e pais textuais.** Buscar com trechos menores e recuperar
   a seção de origem, incluindo definições e notas. Alterar o fingerprint da
   ingestão ao mudar a divisão dos documentos.
3. **Criar busca global por comunidades.** Detectar comunidades sobre relações
   de domínio selecionadas, evitando que simples adjacências de página dominem
   os agrupamentos. Gerar resumos vinculados aos trechos originais, persistir
   sua versão e distinguir perguntas locais de perguntas globais no roteador.

Exemplo local: “Qual foi a variação da indústria paulista em dezembro de 2025?”.
Exemplo global: “Quais temas e relações econômicas aparecem nos boletins?”.
O segundo depende de cobertura do corpus, que não é garantida pelos primeiros
resultados de uma busca por similaridade. O catálogo descreve a recuperação dos
resumos de comunidades de um nível, possivelmente em lotes; escolher apenas os
mais similares muda a cobertura do método.

## Avaliação para o TCC

Comparar RAG tradicional, RAG com expansão pelo grafo e RAG com comunidades usando
o mesmo corpus, modelos, configurações de trechos e orçamento de contexto nas
etapas compartilhadas. Separar perguntas locais e globais; medir evidências
recuperadas, fidelidade às fontes, abrangência, latência e custo.

As versões atuais `rag_simples` e `graphrag` usam configurações diferentes de
embeddings e recuperação. Uma comparação direta não isola o efeito do grafo.
O roteiro `scripts/evaluate_retrieval.py` já oferece modos de ablação no projeto
maior, mas exigiria extensão para comparar o fluxo global proposto.

Esta análise não altera a implementação nem comprova ganhos de qualidade.
