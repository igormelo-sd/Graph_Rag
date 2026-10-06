# Usando o Graph_Rag em um TCC

Este repositório fornece uma base para investigar perguntas sobre documentos econômicos em português. A contribuição científica depende de uma pergunta delimitada, revisão bibliográfica, gabaritos confiáveis e resultados reproduzíveis; o código disponível não demonstra originalidade ou ganho de qualidade por si só.

Veja [Detalhes técnicos](PYTHON.md) e [Confiabilidade](CONFIABILIDADE.md). As alterações atuais não foram testadas e nenhuma avaliação foi executada.

## Recortes possíveis

| Tema | Pergunta experimental |
|---|---|
| Grafo | Costura estrutural e relações extraídas melhoram recuperação e respostas? |
| Busca híbrida | Combinar BM25 e vetor supera cada busca isolada? |
| Rerank | Como BGE, LLM e scores alteram qualidade, latência e custo? |
| Tabelas | Chunking por linha preserva contexto suficiente para cálculos? |
| Ontologia | Observações, relações tipadas e dimensões compartilhadas reduzem confusões semânticas? |
| Validação | A verificação contextual detecta trocas de período, região, indicador e unidade? |

Defina uma hipótese antes de escolher métricas. Alegações sobre lacunas da literatura precisam de referências, não apenas da existência do projeto.

## Gabarito e protocolo

Prepare, por exemplo, 50–100 perguntas factuais, comparativas, setoriais, regionais e sem resposta no corpus. Para cada uma, registre resposta esperada e arquivo/página com o trecho que a sustenta. Separe perguntas de desenvolvimento das de avaliação final e revise o gabarito com outra pessoa quando possível.

`evaluation/cases.example.jsonl` é apenas um rascunho. Copie-o para um arquivo de casos, preencha `expected_sources`, `expected_answer_contains` e marque `gold_reviewed=true` somente depois de conferir os PDFs. Não coloque o gabarito no índice.

`scripts/evaluate_retrieval.py` prepara híbrido, estrutural e grafo LLM, cada um com ativação/desativação parcial da ontologia, em processos separados, com as mesmas fontes base, sem HyDE/deep search ou reescrita variável. Esse roteiro não implementa automaticamente todas as ablações possíveis. Busca somente vetorial, somente BM25 e outras variantes exigem adaptação explícita do código ou do harness; não são todas flags do `.env`.

Registre configuração completa, modelos, corpus, manifesto, versão do código, erros e repetições. Diferencie cache frio de aquecido e custo de construção de custo por consulta. Inicialização aparece separadamente em `startup_seconds` e `startup_usage`.

## Métricas e limites

| Medida | Interpretação |
|---|---|
| Recall documental do harness | Recuperação dos arquivos esperados; não equivale a recall de trechos ou MRR |
| Correspondência de fragmentos | Aproximação textual; não é acurácia semântica |
| Avaliação humana cega | Correção, suficiência, apoio documental e comparabilidade dos dados |
| Validação numérica | Heurística por ocorrência; medir precisão/recall com erros rotulados |
| Latência e erros | Separar inicialização, consulta, filas e falhas; calcular percentis com dados brutos suficientes |
| Tokens e custo | Uso reportado quando disponível; custo desconhecido permanece nulo |
| Recusa | Avaliar perguntas sem resposta no corpus, incluindo contexto recuperado insuficiente |

RAGAS ou outro avaliador pode complementar a revisão humana, com limitações explicitadas. Validador numérico e correspondência textual não demonstram faithfulness de toda a resposta. Cálculos exigem avaliar tanto a conta quanto a escolha semântica dos operandos.

Repita condições e reporte dispersão. Temperatura zero não garante determinismo. Escolha testes estatísticos conforme desenho e distribuição dos dados, sem presumir um método adequado antes de examinar o protocolo.

## Reprodutibilidade

Preserve `main.py`, `src/`, as skills e arquivos de roteamento em `.agents/`, `scripts/`, `evaluation/`, testes relevantes, corpus permitido e entradas/locks de dependências. Omitir skills muda o prompt de síntese.

Os locks existentes incluem versões e hashes para Windows x64/Python 3.11; não substituí-los por um `pip freeze` sem justificativa. Pesos dos modelos e ferramentas externas precisam de registro separado. Use índice compatível com o pipeline atual e modo somente leitura durante comparação controlada.

Não versione chaves ou caches gerados; documente como reproduzir a preparação. Embeddings locais não tornam toda a aplicação privada se trechos forem enviados ao LLM remoto.

## Organização do trabalho

Para a fundamentação sobre atenção e a arquitetura Transformer, consulte **Vaswani et al. (2017), [Attention Is All You Need](https://arxiv.org/abs/1706.03762)** ([PDF](https://arxiv.org/pdf/1706.03762)). O artigo apresenta o Transformer, arquitetura que fundamenta muitos LLMs atuais; seus experimentos originais tratam de tradução automática. Use-o para explicar self-attention, atenção multi-head e codificação posicional.

1. Introdução: problema, escopo, hipótese e objetivos.
2. Fundamentação e trabalhos relacionados: recuperação, síntese, grafos e avaliação, com fontes bibliográficas.
3. Metodologia: corpus, gabarito, condições, métricas, revisões e critérios de exclusão.
4. Implementação: decisões do sistema e mudanças feitas para o experimento.
5. Resultados: medidas observadas, incerteza e análise de erros.
6. Conclusão: resposta à hipótese, limitações e trabalho futuro.

Planeje primeiro revisão e ambiente, depois gabarito e piloto, em seguida experimentos e escrita. Declare uso de IA conforme normas institucionais e diferencie contribuição própria do código-base. As tabelas de resultados devem conter apenas medidas efetivamente obtidas, nunca estimativas apresentadas como experimentos.

## Aplicações da ontologia no projeto

A ontologia define conceitos, propriedades e relações do domínio; o embedding representa conteúdos em vetores para recuperação por similaridade. A ontologia pode orientar componentes com ou sem vetorização do grafo. Consulte a [pesquisa sobre ontologia](PESQUISA_ONTOLOGIA.md) para fundamentos e diagnóstico do código.

O modelo compartilhado em `src/domain_ontology.py` fornece conceitos, dimensões e contratos aos componentes. `OntologyPathExtractor` valida relações; propostas descobertas só entram após aprovação humana. Observações podem ser consultadas localmente por dimensões, e `LLMSynonymRetriever` é opcional. Não há retriever vetorial do grafo explicitamente registrado em `GraphRetriever`.

O acoplamento anterior foi removido: embedding e descoberta não ativam extração de relações por LLM, e descoberta isolada pode iniciar o grafo. A ontologia também participa dos componentes sem grafo. Esta alteração foi implementada sem execução de testes ou avaliação.

As aplicações abaixo receberam implementação inicial. Sua compatibilidade em execução e seus ganhos ainda não foram verificados; veja [ONTOLOGIA.md](ONTOLOGIA.md) para cobertura e limites:

| Etapa | Aplicação implementada inicialmente | Componentes relacionados |
|---|---|---|
| Ingestão | Identificar indicador, valor, unidade, período, território e recortes aplicáveis como observações com proveniência | `ingestion.py`, `processing.py` |
| Indexação | Armazenar identificadores canônicos e dimensões normalizadas nos metadados dos chunks para filtros e rastreabilidade | `indexing.py`, `index_manifest.py` |
| Interpretação | Reconhecer entidades e distinguir nível, saldo, taxa e variação na pergunta, preservando ambiguidades | `query_interpreter.py` |
| Busca híbrida | Expandir aliases controlados e filtrar candidatos pelas dimensões, sem depender de um grafo | `text_retriever.py` |
| Grafo | Representar entidades, observações e relações com definições e tipos explícitos | `graph_ontology.py`, `graph_indexing.py`, `graph_retriever.py` |
| Tabelas e cálculos | Conferir se operandos têm indicador, unidade, cobertura e períodos compatíveis com a operação | `tables_retriever.py`, `timeseries_retriever.py`, `calculations.py` |
| Síntese e evidências | Compartilhar definições de domínio e relacionar afirmações às observações documentais | `analysis_engine.py`, `evidence.py`, `numerical_validator.py` |
| Avaliação | Preparar seis condições e registrar dimensões/candidatos para revisão; o indicador automático de competência mede reconhecimento na pergunta | `scripts/evaluate_retrieval.py`, `evaluation/` |

Foram implementadas as quatro frentes: observações estatísticas, relações tipadas, normalização de entidades e uso do modelo na consulta. Definições semânticas e validação de conformidade devem ter funções distintas. Nem uma estrutura válida nem uma conta correta garantem que a fonte sustente os dados escolhidos.

A evolução seguinte acrescenta associação por célula/cabeçalho, contexto documental por arestas, qualificadores de relações, grafos de derivação, divergências candidatas, esclarecimento de ambiguidades, hierarquia e cobertura. Consulte [ESTATISTICAS_GRAFO.md](ESTATISTICAS_GRAFO.md). São implementações sem verificação em execução; a contribuição experimental precisa medir ligação valor/período, recuperação de notas, falsos conflitos, pedidos de esclarecimento e preservação da modalidade. Contagens automáticas não demonstram acurácia nem ganho.

## Referências para a fundamentação

As referências abaixo são fontes conceituais e técnicas; não demonstram resultados do Graph_Rag. Adapte a apresentação bibliográfica às normas da instituição.

- **VASWANI, Ashish et al. (2017).** *Attention Is All You Need*. [Artigo no arXiv](https://arxiv.org/abs/1706.03762) · [PDF](https://arxiv.org/pdf/1706.03762). Fundamentação da arquitetura Transformer e dos mecanismos de atenção.
- **GRUBER, Thomas R. (1993).** *A Translation Approach to Portable Ontology Specifications*. Knowledge Acquisition, v. 5, n. 2, p. 199–220. [Página do autor](https://tomgruber.org/writing/ontolingua-kaj-1993/) · [PDF](https://tomgruber.org/writing/ontolingua-kaj-1993.pdf). Definição clássica de ontologia e compartilhamento de conhecimento entre sistemas.
- **GRUBER, Tom (2009).** *Ontology*. In: LIU, Ling; ÖZSU, M. Tamer (org.). Encyclopedia of Database Systems. Springer. [Verbete em PDF](https://tomgruber.org/writing/definition-of-ontology.pdf). Nível semântico, significado e diferentes graus de formalização.
- **NOY, Natalya F.; McGUINNESS, Deborah L. (2001).** *Ontology Development 101: A Guide to Creating Your First Ontology*. Stanford. [Guia](https://protege.stanford.edu/publications/ontology_development/ontology101-noy-mcguinness.html). Domínio, escopo, perguntas de competência e desenvolvimento iterativo.
- **W3C (2012).** *OWL 2 Web Ontology Language Primer (Second Edition)*. [Documento](https://www.w3.org/TR/owl2-primer/). Classes, indivíduos, propriedades, axiomas e distinção entre inferência e validação.
- **W3C (2009).** *SKOS Simple Knowledge Organization System Primer*. [Documento](https://www.w3.org/TR/skos-primer/). Conceitos, rótulos preferidos e alternativos e relações hierárquicas.
- **W3C (2014).** *The RDF Data Cube Vocabulary*. [Recomendação de 16 de janeiro de 2014](https://www.w3.org/TR/2014/REC-vocab-data-cube-20140116/). Observações estatísticas, dimensões, medidas e atributos, como unidade e escala.
- **W3C (2017).** *Shapes Constraint Language (SHACL)*. [Documento](https://www.w3.org/TR/shacl/). Restrições e validação de conformidade de grafos RDF; não substitui verificação documental.
