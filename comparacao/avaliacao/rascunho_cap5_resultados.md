# Rascunho do capítulo 5: Testes, resultados e discussão

Rascunho para o template de Protótipo do manual. Os trechos entre `[PREENCHER]`
dependem da rubrica humana, ainda não aplicada. Os números vêm de
`teste_20261104_r1..r3` e do registro `congelamento_20261104.json`. A redação final
é do grupo, e o uso de IA deve ser declarado conforme a seção 8 do manual.

## 5.1 Procedimento de teste

Foram comparadas duas versões sobre o mesmo corpus estatístico de 20 arquivos do
Estado de São Paulo: um RAG simples e um GraphRAG. Uma terceira versão (`rag_pais`),
que amplia o contexto com o trecho pai mas não usa o grafo, serviu de ablação, para
separar o efeito do contexto ampliado do efeito do grafo. As três partem dos mesmos
cinco trechos iniciais e usam o mesmo perfil: busca híbrida com reordenação
(`BAAI/bge-reranker-v2-m3`), embeddings `text-embedding-3-small` e geração com
`gpt-4o-mini`, temperatura 0.

O ajuste do GraphRAG usou somente 20 perguntas de desenvolvimento. Antes da primeira
execução do conjunto de teste, código, parâmetros, índice e perguntas foram
congelados e identificados por hash. O teste tem 50 perguntas, sorteadas de forma
estratificada: 12 factuais, 12 numéricas, 10 de integração, 8 de síntese e 8 de
limites do corpus. Cada versão respondeu a cada pergunta em 3 rodadas, em ordem
alternada, totalizando 450 execuções.

Foram usadas duas medidas:

- **Cobertura do gabarito**: quantas das 94 referências documentais do gabarito
  aparecem no contexto enviado ao modelo. Mede a recuperação, não a resposta.
- **Rubrica humana cega**: correção, apoio documental, completude e qualificação,
  de 0 a 2 cada (total de 0 a 8), aplicada às respostas da rodada 1, sem identificação
  da versão.

## 5.2 Integridade da execução

As 450 execuções terminaram sem erros, em cerca de duas horas (04/11/2026, das
12:49 às 14:50), com o corpus inalterado. Os cinco trechos iniciais foram iguais nas
três rodadas em 49 das 50 perguntas; na T093, o quinto trecho mudou na rodada 2, nas
três versões. Mesmo com temperatura 0, as respostas não foram textualmente idênticas
nas três rodadas na maior parte das perguntas: isso ocorreu em 12 perguntas no RAG
simples, 9 no GraphRAG e 8 no `rag_pais`, de 50.

## 5.3 Recuperação

**Tabela 1: Referências do gabarito no contexto e custo por versão (medianas das 150
execuções de cada versão)**

| Versão | Referências (de 94) | Contexto | Recuperação | Geração |
|---|---:|---:|---:|---:|
| RAG simples | 30 | ~1,1 mil tokens | 19 s | 1,8 s |
| `rag_pais` | 30 | ~2,1 mil tokens | 19 s | 1,7 s |
| GraphRAG | 35 | ~3,2 mil tokens | 37 s | 1,8 s |

**Tabela 2: Referências do gabarito no contexto por categoria**

| Categoria | Referências | RAG simples | `rag_pais` | GraphRAG |
|---|---:|---:|---:|---:|
| Factual | 13 | 11 | 11 | 11 |
| Numérica | 15 | 2 | 2 | 4 |
| Integração | 26 | 8 | 8 | 8 |
| Síntese | 30 | 6 | 6 | 9 |
| Limites | 10 | 3 | 3 | 3 |

A cobertura foi igual nas três rodadas. O GraphRAG ganhou 5 referências, em 5
perguntas, e não perdeu nenhuma. Como o `rag_pais` não ganhou nenhuma, o ganho vem
do grafo, e não do contexto ampliado. O ganho aparece nas categorias numérica e de
síntese; em factual, integração e limites, não há diferença.

O efeito é pequeno e seu custo é real: o GraphRAG enviou cerca de três vezes mais
contexto que o RAG simples, e a recuperação levou o dobro do tempo. Dos 453 trechos
acrescentados pelo grafo, 67 foram citados nas respostas (14,8%), em 52 das 150
respostas. Esse aproveitamento é maior que o da versão anterior do grafo, medido nas
perguntas de desenvolvimento (1,5%), mas a maioria dos trechos acrescentados continua
sem uso explícito.

Referência no contexto não garante resposta melhor. Das cinco perguntas com ganho, só
na T032 o valor da resposta mudou: de -1,3% (errado) para -1,6% (correto). Na T042, as
duas versões dão o mesmo valor, e a resposta do GraphRAG não cita o trecho novo.

Nas três versões, 59 das 94 referências ficaram fora do contexto. Essa é a principal
limitação observada, e o grafo a resolve pouco: seus candidatos, antes da seleção,
continham 31 referências. Há recusa de referências propostas em apenas quatro
perguntas (T016, T058, T076 e T085), portanto o problema é sobretudo de alcance, e não
de seleção. A cobertura é mais baixa nas perguntas que exigem várias fontes, nas quais
cinco trechos iniciais dificilmente alcançam todas as referências.

## 5.4 Qualidade das respostas

[PREENCHER depois de `cega.py pontuar`: médias de RAG simples e GraphRAG, geral, por
categoria e por componente da rubrica; perguntas com maior diferença; decisões de
revisão do gabarito registradas na ficha.]

[PREENCHER: a discussão deve dizer se o ganho de recuperação se traduziu em respostas
melhores. Se a diferença for pequena ou desfavorável ao GraphRAG, esse é o resultado,
e a conclusão do capítulo 6 deve refletir isso.]

## 5.5 Limitações

- **Avaliação**: a rubrica cobre só a rodada 1 e as versões `rag_simples` e `graphrag`.
  [PREENCHER: quem avaliou, e se participou do ajuste.]
- **Gabaritos**: foram aprovados pelo autor, com conferência assistida por IA
  (`revisao_teste_20261103.md`), sem revisor independente. Os valores foram conferidos
  contra o corpus, mas a aprovação não é cega.
- **Medida de cobertura**: é conservadora. Em planilhas, exige o valor e o rótulo da
  linha no mesmo trecho; na T042, o RAG simples deu o valor correto sem que a
  referência fosse contada.
- **Amostra**: 50 perguntas e 5 referências ganhas não permitem generalizar. O resultado
  vale para este corpus e este perfil. Nenhuma das 50 perguntas acionou comunidades,
  logo essa parte do GraphRAG não foi avaliada.
- **Reprodutibilidade**: os modelos da OpenAI são remotos e podem mudar sob o mesmo
  nome; a identidade reportada pela API não foi registrada. O ambiente local usou
  Python 3.13, e os locks do repositório visam Python 3.11.

## 5.6 Melhorias futuras

- Aumentar o alcance nas perguntas de várias fontes, por exemplo decompondo a pergunta
  em subperguntas ou ampliando o ranking inicial nessas categorias.
- Reduzir o tempo de recuperação do GraphRAG, hoje dominado pela reordenação dos
  candidatos do grafo em CPU.
- Testar perguntas globais, para avaliar as comunidades do grafo.
- Fazer a avaliação com mais de um avaliador e medir a concordância entre eles.
