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
| Ontologia | Tipos adicionais melhoram extração sem aumentar ruído? |
| Validação | A verificação contextual detecta trocas de período, região, indicador e unidade? |

Defina uma hipótese antes de escolher métricas. Alegações sobre lacunas da literatura precisam de referências, não apenas da existência do projeto.

## Gabarito e protocolo

Prepare, por exemplo, 50–100 perguntas factuais, comparativas, setoriais, regionais e sem resposta no corpus. Para cada uma, registre resposta esperada e arquivo/página com o trecho que a sustenta. Separe perguntas de desenvolvimento das de avaliação final e revise o gabarito com outra pessoa quando possível.

`evaluation/cases.example.jsonl` é apenas um rascunho. Copie-o para um arquivo de casos, preencha `expected_sources`, `expected_answer_contains` e marque `gold_reviewed=true` somente depois de conferir os PDFs. Não coloque o gabarito no índice.

`scripts/evaluate_retrieval.py` prepara híbrido, estrutural e grafo LLM em processos separados, com as mesmas fontes base, sem HyDE/deep search ou reescrita variável. Esse roteiro não implementa automaticamente todas as ablações possíveis. Busca somente vetorial, somente BM25 e outras variantes exigem adaptação explícita do código ou do harness; não são todas flags do `.env`.

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
