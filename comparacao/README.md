# Comparação entre RAG simples e GraphRAG

Organização do código e execução de todas as suítes: [guia de manutenção](../docs/REFATORACAO.md).

O perfil comum está em [config.json](config.json). Ele é aplicado como padrão nos
dois aplicativos e imposto nos comandos de comparação: variáveis locais de modelo,
recuperação ou endpoint não podem substituir o perfil nessa execução.

| Parâmetro | Valor comum |
|---|---|
| Provedor / modelo de resposta | OpenAI / `gpt-4o-mini` |
| Embeddings | OpenAI `text-embedding-3-small` (`embedding_provider: "openai"`), normalizados |
| Lote do embedding | 128 trechos por requisição |
| Trechos / sobreposição | 1.024 / 200 caracteres, SentenceSplitter |
| Busca inicial | Híbrida: cosseno exato + BM25, 50 candidatos de cada, fusão RRF (k=60), reranking dos 30 primeiros com `BAAI/bge-reranker-v2-m3` (local, CPU), no máximo 2 trechos por tabela, 5 trechos |
| Contexto de evidências | Até 12.000 tokens estimados por caracteres / 4 |
| Resposta máxima / temperatura | 1.200 tokens / 0 |
| Corpus | `../data` |

Também são iguais o prompt final, a numeração de fontes e a política de incluir
trechos inteiros que caibam no orçamento. O limite de contexto é uma estimativa;
não corresponde a uma contagem exata do tokenizer do modelo.

`embedding_provider` aceita `openai` ou `huggingface`; perfis sem o campo usam
`huggingface` (local, com `embedding_device` e `embedding_max_length`). Com
`openai`, os trechos e as perguntas são enviados à API para vetorização, e a
chave `OPENAI_API_KEY` é lida de `comparacao/.env` ou, na ausência, somente essa
chave do `.env` da raiz. Os modelos da OpenAI podem mudar sob o mesmo nome;
registre a data da preparação.

### Ranking inicial e contexto comuns

As etapas abaixo ocorrem antes de `strategy.retrieve()` ou no prompt final, então
valem igualmente para as duas versões; o grafo continua sendo a única diferença.

- **Busca híbrida** (`retrieval_mode: "hybrid"`, em `comparacao/retrieval.py`):
  os `candidate_pool` primeiros da busca vetorial e do BM25 são combinados por
  Reciprocal Rank Fusion (`rrf_k`). O BM25 tokeniza sem acentos e mantém códigos
  e números inteiros (`47.32-6`, `3.277,8`), que a busca vetorial não distingue
  bem. `dense` desativa o BM25. Cada resultado registra `initial_ranks`, a
  posição do trecho em cada lista.
- **Reranking** (`reranker`, `rerank_pool`): um cross-encoder local lê pergunta
  e trecho juntos e reordena os `rerank_pool` primeiros da fusão. Recupera trechos
  que as duas buscas deixam em posições baixas. O ranking inicial é calculado uma
  vez por pergunta e compartilhado pelas versões; `initial_ranking_seconds` entra
  no `retrieval_seconds` de ambas. Texto vazio desativa o reranking.
- **Diversificação** (`max_per_table`): no máximo N trechos da mesma tabela entre
  os iniciais, mantendo a ordem; linhas quase idênticas de uma tabela deixavam de
  ocupar todas as vagas. `0` desativa o limite.
- **Rodapés de planilha** (`comparacao/footnotes.py`): linhas de linha única que
  começam com "Fonte", "Nota", "(1)", "(...)" etc. não viram trechos. O texto
  delas acompanha as demais linhas da tabela em `table_footnotes` e aparece no
  contexto como "Notas da tabela". Isso altera o preparo (`PIPELINE` v2).
- **Fragmentos curtos** (`min_text_chars`, `comparacao/chunk_repair.py`): trechos
  de texto menores que o limite, em geral sobras de quebra de página, também são
  anexados ao trecho anterior da mesma fonte. O fragmento continua no índice
  para não romper a sequência usada pelas arestas do grafo.
- **Tabelas pequenas** (`small_table_rows`, `small_table_chars`): tabelas que o
  processamento dividiu em uma linha por trecho voltam a ser um trecho único
  quando têm até N linhas e cabem no limite de caracteres, como os dicionários
  de variáveis. Esses dois reparos definem o `PIPELINE` v3.
- **Prompt**: pede território, período, base e unidade para cada número, que só
  atribua números presentes na mesma fonte, que aponte perguntas ambíguas, que não
  afirme a cobertura do corpus além das fontes e que cite notas aplicáveis.

Perfis sem esses campos usam `dense`, `candidate_pool = top_k`, sem reranking,
sem limite por tabela e sem reparos de trechos, ou seja, a busca inicial anterior.

Perguntas sobre uma célula específica de séries longas (por exemplo, D010) não
são resolvidas por essas etapas: a linha certa fica fora dos candidatos das duas
buscas, porque centenas de linhas compartilham o mesmo título e cabeçalho.

## Limitação: tabelas com mais de 1.000 linhas

A ingestão gera um trecho por linha de tabela, com teto de 1.000 linhas por
tabela (`RAG_TABLE_MAX_ROWS_PER_TABLE`, padrão do GraphRAG). O teto foi mantido
na comparação; linhas além dele **não recebem embedding** e não podem ser
recuperadas por nenhuma das duas versões, pois os comandos controlados não usam
busca tabular. No corpus atual, ficam truncados:

| Arquivo | Linhas | Indexadas |
|---|---:|---:|
| `pib_municipal_2002_2020.csv` | 85.785 | 1.000 |
| `base-pmc_spbrasil.csv` | 15.582 | 1.000 |
| `base-pim_spbrasil.csv` | 13.652 | 1.000 |
| `base-pms_spbrasil.csv` | 4.490 | 1.000 |

Perguntas cujo gabarito cita linhas fora do índice: D011 e D018
(desenvolvimento); T046–T055, T065, T082, T087, T088, T094 e T095 (teste).
Analise-as separadamente: um erro nelas mede o teto de ingestão, não a
diferença entre as estratégias de recuperação. Nas perguntas de ausência de
informação desse grupo, uma recusa correta pode ocorrer sem que a evidência
do gabarito tenha sido recuperada.

Na preparação de 26/10/2026, o índice teve 27.091 trechos (1.013 de texto e
26.078 de tabelas); `01-2026-tabelas-pib-regional-site.xlsx` sozinho gerou
17.706. Na de 27/10/2026, com os rodapés convertidos em notas, ficaram 26.591
trechos (500 linhas de rodapé a menos). Esse desequilíbrio pode reduzir a presença de trechos dos PDFs entre
os 5 resultados iniciais. Na de 28/10/2026 (`PIPELINE` v3), ficaram 25.896.

## Versão v4: RAG simples sem grafo e GraphRAG sobre o mesmo código

`PIPELINE` `shared-graph-processing-v4`. Esta versão **não** é a configuração
congelada de 04/11 (abaixo): o perfil, o índice e o comportamento do `simple_rag`
mudaram, então os resultados anteriores não são comparáveis. Objetivo: a única
diferença entre as versões passa a ser o grafo.

| Aspecto | `simple_rag` | `graph_rag` |
|---|---|---|
| Código (`simple_rag/src` e `graph_rag/src`): preparo, índice, ranking inicial, reranker, ontologia (anotação e filtro), prompt | idêntico, byte a byte (teste em `tests_shared/test_implementations.py`) | idêntico |
| Módulos de grafo (`graph_indexing`, `graph_retriever`, `graph_ontology`, `ontology_extractor`, `relation_semantics`, `community_search`) | **não existem na pasta** | existem |
| Módulos com ganchos de grafo (`analysis_engine`, `startup`, `query_interpreter`) | versão sem grafo | versão com grafo |
| Trechos iniciais | `top_k` do ranking comum | os mesmos |
| Vagas extras | próximos `baseline_extra_slots` (6) trechos do ranking comum (reserva) | até 6 candidatos do grafo aceitos pelo reranker |
| Trechos pais literais | sim | sim |
| Grafo (entidades, rótulos, contexto documental, observações, comunidades) | **nenhum** | sim |

- **Índice por pasta:** `preparar` calcula os vetores uma vez em
  `simple_rag/indice/index.json` e copia os mesmos bytes para
  `graph_rag/indice/index.json`; cada pasta recebe `manifesto.json` com o SHA-256.
  `perguntar`, `avaliar` e `cobertura` recusam a execução se um índice faltar ou se
  os hashes divergirem; o hash também entra no manifesto de cada rodada.
- **Reserva:** o ranking comum é calculado com `top_k + baseline_extra_slots`
  posições; os `top_k` primeiros são idênticos aos de antes. O limite de 6 é o
  máximo do GraphRAG, que costuma aceitar menos; o RAG simples fica, se algo,
  com vantagem de contexto.
- **Filtro de ontologia comum** (`ontology_filter`): candidatos em conflito explícito
  com indicador, território, período, unidade, escala ou setor da pergunta saem do
  ranking inicial das duas versões. Dados incompletos permanecem.
- **Processo próprio:** `avaliar --versoes simple_rag` (ou `simple_rag,parent_rag`) e a CLI do
  `simple_rag` carregam só `simple_rag/src`; com `graph_rag` na lista, o processo usa
  `graph_rag/src`. Rodadas das duas versões podem ir para a mesma `--saida` em comandos
  separados (a retomada mantém o que já foi gravado), perdendo a alternância de ordem.
  A raiz do repositório não tem código de RAG.
- **Comandos do `simple_rag`:** `indexar` chama o mesmo `preparar`; `perguntar` e
  `comparar` usam a mesma recuperação do `avaliar`. O caminho antigo (`pypdf` e
  `SentenceSplitter`) não é mais usado pela CLI.
- **Não executado:** esta versão não foi testada nem preparada; exige novo
  `preparar` (embeddings pagos), novas rodadas e novo registro de congelamento.

## Resultados da v4 no conjunto de desenvolvimento (12/11/2026)

Rodada `v4_dev_20261112_r1`: 20 perguntas, `simple_rag` e `graph_rag` em processos separados
(`avaliar --versoes simple_rag` e depois `--versoes graph_rag`, mesma `--saida`), índice de 25.896
trechos (SHA-256 `2a17c93a…`, igual nas duas pastas), perfil `d7da9383…`, `PIPELINE` v4, `gpt-4o-mini`,
`text-embedding-3-small`, reranker `BAAI/bge-reranker-v2-m3`. 40 execuções, sem erros. Os 5 trechos
iniciais foram iguais nas duas versões em 20 de 20 perguntas.

| Medida | `simple_rag` | `graph_rag` |
|---|---:|---:|
| Marcadores literais (de 34, `avaliacao/marcadores.py`) | 24 | 24 |
| Referências do gabarito no contexto enviado ao modelo (de 39) | 23 | 23 |
| Contexto (mediana, tokens estimados) | ~4,4 mil | ~4,0 mil |
| Recuperação (mediana) | 15,5 s | 32,1 s |
| Extras aceitos do grafo (média por pergunta) | — (6 de reserva) | 4,0 (nenhum em 4 de 20) |

- **Empate.** O grafo não superou o RAG simples nesta rodada. Diferenças por pergunta: nos marcadores,
  D001 (ICMS) é 1 a 0 para o `simple_rag` e D014 é 3 a 2 para o `graph_rag`; na cobertura do gabarito,
  D008 é 1 a 0 para o `graph_rag` (candidatos por rótulo) e D017 é 2 a 1 para o `simple_rag`.
- **Custo.** O tempo de recuperação do `graph_rag` é o dobro, com contexto de tamanho parecido.
  Em 4 das 20 perguntas o grafo não teve candidato aceito.
- **Por que o simples melhorou.** Na rodada de 03/11, o `simple_rag` tinha 22 marcadores e o
  `graph_rag` 23,7. Agora o simples usa os mesmos trechos pais e a mesma quantidade de vagas
  (reserva de 6 trechos do ranking comum), e o filtro de ontologia vale para os dois. Com isso o
  ganho que antes se atribuía ao grafo ficou, em grande parte, nas etapas comuns.
- **Limites desta leitura.** Uma única rodada; marcadores são triagem automática (variação de cerca
  de 1 marcador entre rodadas em medições anteriores); as respostas não passaram pela rubrica humana;
  o conjunto de desenvolvimento foi o usado para ajustar o grafo em 03/11 e a cobertura é determinística
  (a variação vem só da geração). Não houve rodada no conjunto de teste, que segue reservado.
- **Não foi feito:** melhorias do grafo (ranking dos candidatos, unificação de entidades, evidência
  normalizada) e a incorporação das melhorias de ingestão e embedding do `cd9ff90`. Ficam para o
  planejamento do próximo passo, medindo cada uma nas duas versões.

## Passo 1: tabelas longas e dicionários (12/11/2026)

Motivo: na rodada `r1`, 15 das 39 referências do gabarito ficavam fora do contexto das duas versões; 11 eram
linhas de CSV ou dicionários (`dicvar_*`, `dic_variaveis_*`) e 2 estavam além do teto de 1.000 linhas por tabela.

Mudanças **comuns às duas versões** (`comparacao/`, perfil `structured_lookup: true`):
- **Busca literal no corpus tabular inteiro** (`rag_app/structured_lookup.py`, sem LLM e sem o teto de linhas).
  Só as linhas *exatas* (código, célula, município ou catálogo identificados) entram, até 2, à frente do
  ranking (`retrieval.initial_ranking`). As linhas apenas lexicais foram descartadas (veja `r2`).
- **Título e notas da tabela no contexto** (`common.pack_results`): o trecho de uma tabela é uma linha
  "coluna: valor" e o título, que define a série, não chegava ao modelo (70 dos 184 blocos eram linhas de tabela).

Mudanças **só do `graph_rag`**:
- **`DICIONARIO_DE`**: trechos de `dicvar_X` e `dic_variaveis_X` ligados à tabela-base (`X` ou `base-X_*`) pela
  convenção de nomes, só se a base for única (`graph_indexing.dictionary_base_files`).
- **Sementes de apoio**: uma linha exata do corpus inteiro não existe no grafo; usa-se uma linha da mesma tabela
  como ponto de partida da expansão (`GraphVariant.seeds`), sem incluí-la no contexto.
- **Contexto vinculado**: dicionário e notas ligados por essas arestas (até 2) entram sem o limiar do reranker.
- **Pool de entidades raras retirado** (122 propostos, 2 aceitos na `r1`).

| Rodada | Código | `simple_rag` refs / marcadores | `graph_rag` refs / marcadores | Recuperação (s/g) |
|---|---|---:|---:|---:|
| `r1` | base v4 | 23 / 24 | 23 / 24 | 15,5 / 32,1 |
| `r2` | + linhas exatas **e lexicais** | 21 / 24 | 22 / 25 | 16,8 / 34,6 |
| `r3` | só linhas exatas | 25 / 25 | 25 / 25 | 15,4 / 34,7 |
| `r4` | + título e notas; grafo com dicionário | 25 / 27 | 25 / 26 | 16,0 / 31,9 |

(refs = referências do gabarito no contexto enviado ao modelo, de 39; marcadores de 34 por `avaliacao/marcadores.py`.)

- **`r2`:** as linhas lexicais (25 nos contextos, só 1 útil) desalojaram dicionários e trechos úteis (D016 perdeu 4
  referências; D001, 1 marcador). Por isso só as exatas ficaram.
- **`r3`:** as linhas exatas deram +2 referências nas duas versões (D005, D011) e nenhuma regressão.
- **`r4`:** título e notas elevaram os marcadores do `simple_rag` (+2: D010, D014) e do `graph_rag` (+1: D013), sem
  mudar as referências. O dicionário foi anexado em 6 casos (D005, D011, D013, D018), todos com uma linha da
  tabela-base já no contexto; **não recuperou nenhuma referência nova**. O contexto documental aceito subiu de 7 para 13.
- **Leitura:** as melhorias comuns elevaram as duas versões (referências 23→25; marcadores 24→27 no simples,
  24→26 no grafo) e **o empate permanece**: o grafo não superou o simples. As mudanças específicas do grafo não
  geraram ganho mensurável aqui; a latência caiu ~8% (34,7 → 31,9 s) com a retirada do pool de entidades.
- **Dicionários ainda ausentes:** em D014, D016 e D019 o gabarito é o próprio dicionário e a tabela-base também não está
  no contexto; sem semente, a aresta não atua. O problema parece ser de recuperação do dicionário pela pergunta
  (roteamento por tipo de documento), não de ligação entre tabelas. Hipótese a testar, não verificada.
- **Limites:** uma rodada por configuração; conjunto de desenvolvimento (39 referências, ±1 é ruído); marcadores são
  triagem automática; sem rubrica humana. O corte das linhas lexicais e a retirada do pool de entidades foram
  decididos depois de ver resultados do próprio desenvolvimento, então os números tendem a ser otimistas.
  Na `r3`, o `graph_rag` carregou a seleção nova no meio da rodada (campo `linked`), sem efeito (0 vinculados aceitos).
- **Conjunto de teste:** não foi avaliado. Houve uma contagem offline, sem ler as perguntas, de quantas referências
  tabulares a busca literal alcança (8 de 45 no teste, contra 8 de 20 no desenvolvimento); não foi usada para ajustar nada.

## Passo 2: cabeçalho contextual, dicionários, controle lexical e desenho do orçamento (13/11/2026)

Mudanças **comuns às duas versões** (`comparacao/`; chaves do perfil):
- **`contextual_embedding`** (exige reindexar): o embedding e o BM25 de cada trecho levam o cabeçalho "Documento | Tabela
  (título ou descrição) | Aba/Seção"; o texto mostrado ao modelo não muda. Uma linha de tabela ("coluna: valor") não dizia de
  qual tabela veio.
- **`dictionary_routing`**: perguntas com intenção de definição ou de estrutura de classificação (regra de vocabulário geral,
  `retrieval.is_definitional`) também buscam nos dicionários de variáveis (`dicvar_*`, `dic_variaveis_*`), até 3 trechos.
- **Identidade do índice** separada do perfil de consulta (`INDEX_KEYS`): só o que muda o conteúdo do índice exige novo
  `preparar`; o perfil completo identifica a rodada.

**Desenho do orçamento de contexto (correção).** Até a `r6`, o `simple_rag` completava as 6 vagas extras com os próximos trechos
do ranking comum, e o `graph_rag` **descartava essa faixa** e usava só os candidatos do grafo. Como o roteamento de dicionários
coloca dicionários nas posições 6 a 11, o simples os aproveitava e o grafo não (D016: 8 contra 4 referências). Desde a `r8` o
grafo **soma-se** ao ranking: candidatos aceitos primeiro e, depois, os próximos trechos do ranking até o mesmo total de extras
(`variants.fill_with_reserve`). Os números do grafo anteriores à `r8` **não são comparáveis** com os novos.

Novas variantes/ferramentas:
- **`lexical_rag`** (controle sem grafo): mesma seleção pelo reranker e mesmo orçamento, mas os candidatos vêm da expansão lexical
  por tabela e documento (`lexical.py`, termos raros da pergunta), a partir de metadados e não de arestas.
- **`avaliacao/comparar.py`**: comparação pareada por pergunta (diferença de referências, IC95% por bootstrap, teste dos sinais).

Mudanças do grafo (`graph_rag/src`), todas medidas no desenvolvimento:
- **NetworkX** passou a ser a estrutura do grafo (`MultiDiGraph`) para adjacência e algoritmos; o LlamaIndex continua guardando nós
  e relações. A troca preservou o comportamento: 80 de 80 pools (20 perguntas × 4) idênticos em conteúdo e ordem; consultas
  +50% de tempo no total das 80 chamadas, desprezível frente ao reranking.
- **PageRank personalizado** (`retrieve_ppr`, chave `graph_ppr`): multi-salto a partir dos trechos iniciais. Nas 20 perguntas, os
  pools do grafo (~800 candidatos) contêm só 4 referências do gabarito fora dos 5 iniciais, todas no pool de rótulos; o PageRank
  contém 1 e nenhuma exclusiva. **Desligado.**
- **Planejamento por lacunas** (`retrieve_gaps`, chave `gap_planning`): 7 perguntas têm recorte sem apoio e 4 geram candidatos, mas
  todos já eram propostos pelo pool de observações (a deduplicação mantém a primeira origem); efeito nulo na `r9`. **Desligado.**

Rodadas no desenvolvimento (referências do gabarito no contexto, de 39 / marcadores, de 34):

| Rodada | Código | `simple_rag` | `lexical_rag` | `graph_rag` |
|---|---|---:|---:|---:|
| `r4` | linhas exatas, título e notas | 25 / 27 | — | 25 / 26 |
| `r5` | + cabeçalho contextual | 26 / 25 | 21 / 25 | 25 / 26 |
| `r6` | + roteamento de dicionários (grafo sem somar ao ranking) | 30 / 25 | — | 25 / 27 |
| `r8` | grafo e lexical **somam** ao ranking (mesmo orçamento) | **30 / 26** | 26 / 26 | 26 / 27 |
| `r9` | `r8` + planejamento por lacunas (só grafo) | — | — | 26 / 26 |

- **Na `r8`**, o grafo e a lexical empatam em **todas** as 20 perguntas, e o simples fica 4 referências à frente
  (`graph_rag` − `simple_rag` = −4, IC95% −13 a +2, 1 pergunta a favor e 2 contra, p = 1,0), quase tudo na D016.
  Os candidatos do grafo (e da lexical) deslocam trechos do ranking comum; na D016, dicionários.
- **Leitura:** no desenvolvimento, o grafo não supera o RAG simples nem a expansão lexical sem grafo. A vantagem que o grafo
  mostrava sobre a lexical na `r5` (4 referências) vinha do dicionário e do orçamento, e desapareceu com o desenho corrigido.
- **Limites:** uma rodada por configuração; 39 referências (±1 é ruído); marcadores são triagem automática; sem rubrica humana;
  várias decisões (roteamento, corte das linhas lexicais, pool de entidades) foram tomadas olhando o próprio desenvolvimento.

## Troca do modelo de resposta para `gpt-5.4-mini` (13/11/2026)

Antes de concluir as rodadas do conjunto de teste, o modelo de resposta passou de `gpt-4o-mini` para `gpt-5.4-mini`
(a página de modelos da OpenAI marca o `gpt-4o-mini` como "deprecated", o que ameaça a reprodutibilidade). O índice não muda
(o modelo de resposta não faz parte da identidade do índice) e a medida principal automática, as referências do gabarito
no contexto, não depende do modelo, porque a recuperação é determinística.

- **Temperatura:** a fábrica de LLM usa **1,0** com este modelo, e não 0; o perfil passou a declarar `temperature: 1.0`.
  As respostas deixam de ser quase determinísticas e variam mais entre rodadas.
- **Custo:** ~US$ 0,29 por versão e rodada de 50 perguntas (6.462 tokens de entrada e 207 de saída por resposta, medidos em 6
  perguntas de desenvolvimento a US$ 0,75 e US$ 4,50 por milhão); ~US$ 2,02 para as 350 execuções previstas, contra US$ 0,36.
- **Comparação rápida de modelos** (6 perguntas de desenvolvimento, mesmo prompt e mesmo contexto; tempo mediano e marcadores
  de 10): `gpt-4o-mini` 2,2 s e 8; `gpt-5-mini` 14,0 s e 7; `gpt-5` 22,7 s e 10; `gpt-5` com raciocínio mínimo 7,7 s e 10;
  `gpt-5.4-mini` 1,3 s e 10. Amostra pequena: serve para tempo e custo, não para concluir sobre qualidade.
- **Efeito no tempo total:** pequeno, porque a geração é 2 a 3 s dos 20 a 35 s por pergunta (o resto é o reranker na CPU).
- **Congelamento:** `congelamento_20261113_gpt54mini.json` substitui `congelamento_20261113.json`. As 98 respostas já gravadas
  com `gpt-4o-mini` ficaram arquivadas e fora da análise. As rodadas do desenvolvimento (`r1` a `r9`) foram feitas com
  `gpt-4o-mini`; suas referências no contexto valem para qualquer modelo, mas os marcadores, não.

## Resultados anteriores à v4 (registro histórico)

As seções abaixo descrevem as rodadas de 26/10 a 05/11/2026, feitas com a organização anterior:
pastas `rag_simples` e `graphrag`, variante de ablação `rag_pais` e corpus em `graphrag/data`. Os
nomes foram atualizados no texto por consistência (`simple_rag`, `graph_rag`, `parent_rag`), mas
**os arquivos dessas rodadas** em `artefatos/resultados/` e os registros `congelamento_*.json` mantêm
os nomes antigos (`D001_rag_simples.json`, `D001_graphrag.json`). Esses resultados não são
comparáveis com os da v4: o perfil (reserva de trechos, filtro de ontologia, corpus em `data/`) e o
`rag_simples` mudaram. As ferramentas de `avaliacao/` leem os dois nomes.

## Configuração congelada para o TCC (04/11/2026)

A configuração usada nos resultados finais está em
[avaliacao/congelamento_20261104.json](avaliacao/congelamento_20261104.json):
commit `6c894ca`, GraphRAG revisado, 50 perguntas de teste aprovadas (hash
`bed1400c…`) e parâmetros da seleção do grafo. Perfil `d68b280c…`, `PIPELINE` v3,
corpus e índice (`df54c6ed…`) são os mesmos de 28/10. Rodadas:
`teste_20261104_r1..r3`, com `simple_rag`, `graph_rag` e `parent_rag`. Não altere
`config.json`, o código de `comparacao/`, `simple_rag/`, `rag_app/` e
`graph_rag/src` nem as perguntas para novas rodadas desses resultados.

### Resultados de recuperação no teste (3 rodadas, 450 execuções, sem erros)

Rodadas de 04/11, das 12:49 às 14:50, a partir do commit `1b6cf1b`, com corpus
inalterado. Referências do gabarito no contexto, de 94 (o resultado foi igual nas 3
rodadas):

| Versão | Referências | Contexto (mediana) | Recuperação (mediana) | Geração (mediana) |
|---|---:|---:|---:|---:|
| RAG simples | 30 | ~1,1 mil tokens | 19 s | 1,8 s |
| `parent_rag` | 30 | ~2,1 mil tokens | 19 s | 1,7 s |
| GraphRAG revisado | 35 | ~3,2 mil tokens | 37 s | 1,8 s |

| Categoria | Referências | RAG simples | `parent_rag` | GraphRAG |
|---|---:|---:|---:|---:|
| Factual | 13 | 11 | 11 | 11 |
| Numérica | 15 | 2 | 2 | 4 |
| Integração | 26 | 8 | 8 | 8 |
| Síntese | 30 | 6 | 6 | 9 |
| Limites | 10 | 3 | 3 | 3 |

- O GraphRAG ganha 5 referências em 5 perguntas (T032, T042, T076, T077, T085) e
  não perde nenhuma. Duas ressalvas: na T042, o RAG simples responde o mesmo valor
  mesmo sem a referência contada, e a resposta do GraphRAG não cita o trecho novo;
  a T032 é a única das cinco em que o valor numérico da resposta muda (de -1,3%,
  errado, para -1,6%).
- Dos 453 trechos que o grafo acrescentou aos contextos, 67 foram citados (14,8%,
  contra 7% no desenvolvimento e 1,5% em 28/10), em 52 das 150 respostas. Em 30 das
  150 execuções o grafo não teve extra aceito.
- 59 das 94 referências ficam fora do contexto de todas as versões. Os candidatos
  do grafo trazem 31; em T016, T058, T076 e T085 há referência proposta e recusada,
  mas a principal limitação é o alcance, não a seleção.
- A diferença é pequena e a medida é de recuperação: não diz se as respostas
  melhoraram. Isso cabe à rubrica cega da rodada 1 (`cega_teste_r1`, ficha
  `45c8cd18…`), ainda não preenchida. Rascunho do capítulo:
  [avaliacao/rascunho_cap5_resultados.md](avaliacao/rascunho_cap5_resultados.md).

## Configuração congelada anterior (28/10/2026, substituída)


A configuração usada nos resultados do TCC está registrada em
[avaliacao/congelamento_20261028.json](avaliacao/congelamento_20261028.json):
commit `4b2afd8`, perfil `d68b280c…` (`config.json` atual), `PIPELINE` v3,
índice de 25.896 trechos, `gpt-4o-mini` (temperatura 0), `text-embedding-3-small`,
reranker `BAAI/bge-reranker-v2-m3` (revisão `953dc6f`) e as 20 perguntas de
desenvolvimento (hash `4147b379…`). Não altere `config.json`, o código de
`comparacao/`, `simple_rag/`, `rag_app/` e `graph_rag/src` nem as perguntas para
novas rodadas desses resultados. Qualquer mudança exige novo preparo, novas
rodadas e um novo registro de congelamento.

Para conferir uma rodada nova contra o congelamento, compare `profile`,
`pipeline` e `questions_sha256` do `manifesto.json` da rodada com o registro, e o
SHA-256 de `artefatos/index.json` com `indice.sha256`. `artefatos/` não é
versionado: guarde cópia das pastas de resultados e do índice usados no texto.

### Resultados (3 rodadas, 120 execuções, sem erros)

Contagem de marcadores literais dos pontos obrigatórios nas respostas
([avaliacao/marcadores.py](avaliacao/marcadores.py)), de um total de 34:

| Versão | Rodadas 1 / 2 / 3 | Média | Referência anterior (27/10) |
|---|---|---:|---|
| RAG simples | 22 / 21 / 23 | 22,0 | 20 / 20 / 21 (20,3) |
| GraphRAG | 25 / 24 / 24 | 24,3 | 23 / 23 / 22 (22,7) |

```powershell
.\.venv\Scripts\python.exe comparacao/avaliacao/marcadores.py openai_rerank_dev_20261028_r1 openai_rerank_dev_20261028_r2 openai_rerank_dev_20261028_r3
```

- Os 5 trechos iniciais foram idênticos nas 3 rodadas, nas 20 perguntas e nas
  duas versões; a variação vem só da geração. As respostas tiveram texto idêntico
  nas 3 rodadas em 5 (RAG simples) e 6 (GraphRAG) das 20 perguntas.
- A vantagem do GraphRAG (+2,3 marcadores na média) vem de D001 e D014, com +1
  marcador nas 3 rodadas, e de D010 e D020, com +1 em uma rodada. O RAG simples
  só supera o GraphRAG em D016, em uma rodada. Nas outras 15 perguntas, as
  versões empatam em todas as rodadas.
- A referência anterior usou busca híbrida sem reranker nem reparos de trechos e
  o código do GraphRAG antes dos commits de 28/10 (ontologia e esquema do grafo).
  Para o GraphRAG, a diferença entre as duas configurações mistura esses efeitos.

Marcadores são uma triagem automática: medem a presença de números e termos, não
a correção da resposta inteira, o apoio documental ou a qualificação. Os
resultados para o texto devem vir da rubrica aplicada por revisão humana, cega
quanto à versão, depois da revisão dos gabaritos; a ficha da rodada 1 é gerada
por `avaliacao/cega.py` (veja [avaliação cega](avaliacao/README.md#avaliação-cega-pela-rubrica)).

### Limitações conhecidas da configuração congelada

| Perguntas | Limitação | Causa |
|---|---|---|
| D010 | Valor errado nas duas versões | A célula da série longa fica fora dos candidatos: centenas de linhas compartilham título e cabeçalho; exigiria busca tabular |
| D011 | PIB de 2018 não encontrado | A linha está além do teto de 1.000 linhas por tabela |
| D016 | Só a parte de CNAE é respondida | O dicionário do cadastro territorial, mesmo reunido em um trecho, não entra nos 5 iniciais |
| D017 | Não aditividade das séries encadeadas omitida | O trecho com a explicação não entra nos 5 iniciais |
| D018 | Afirmação falsa de cobertura ("dados até 2026") | Geração: o modelo não segue a instrução do prompt |
| D019 | Ambiguidade não apontada | Geração; a resposta escolhe um recorte sem avisar |
| Todas | Ajuste feito no próprio conjunto avaliado | As 20 perguntas orientaram as melhorias; os resultados não medem generalização para perguntas novas |
| Todas | Gabaritos sem revisão humana | `revisao_humana` pendente nas 20 perguntas |
| Todas | Modelos remotos sob nomes estáveis | `gpt-4o-mini` e `text-embedding-3-small` podem mudar; a identidade reportada pela API não foi registrada |
| Todas | Ambiente | Python 3.13 local; os locks do repositório visam 3.11 |

## GraphRAG revisado (03/11/2026)

O código do `graph_rag` mudou depois do congelamento de 28/10/2026, cujos
resultados valem para o commit `4b2afd8`. O índice experimental e o `PIPELINE`
não mudaram; o grafo é montado na sessão.

O diagnóstico das rodadas de 28/10 mostrou que o grafo acrescentava ~11 trechos
por pergunta (contexto de ~6,5 mil tokens contra ~1,1 mil do RAG simples), e só
10 dos 651 trechos acrescentados nas 3 rodadas foram citados nas respostas. Os
vizinhos eram escolhidos pela ordem dos IDs (312 de 366 IDs hexadecimais abaixo
de `0x20`), com escore fixo e sem reranking. Mudanças, todas gerais:

1. **Entidades por raridade** (`GraphRetriever.retrieve_entity_context`): cada
   vizinho soma o IDF das entidades que compartilha com as sementes, dividido
   pela posição da semente; entidades citadas por mais de 2% dos trechos não
   servem de ponte.
2. **Rótulos raros na tabela e no documento** (`label_candidates`): trechos da
   tabela ou do documento das sementes que repetem termos raros da pergunta.
3. **Contexto documental sem linhas irmãs**, com continuidade do texto entre
   páginas consecutivas (`NEXT_CHUNK`, `method: page_boundary`).
4. **Busca guiada pela pergunta** (observações por recorte) também propõe candidatos.
5. **Co-dimensões das observações**: `Indicador MEDIDO_POR FonteDados` e
   `Indicador RELACIONA_COM Setor`, marcadas como coocorrência, não associação.
6. **O reranker decide** ([graph_selection.py](graph_selection.py)): todos os
   candidatos são pontuados pelo mesmo cross-encoder do ranking inicial e entram
   no máximo 6, com escore de pelo menos 0,25 do menor escore inicial da pergunta.

A variante experimental `graph_rag_v2` foi incorporada e removida.

### Cobertura do gabarito, sem API

[avaliacao/cobertura.py](avaliacao/cobertura.py) reaproveita os 5 trechos
iniciais gravados numa rodada, o índice local e o reranker local, e conta as
referências do gabarito presentes no contexto que cada versão enviaria ao modelo.
Nas 20 perguntas de desenvolvimento (39 referências), a partir de
`openai_rerank_dev_20261028_r1`:

| Versão | Referências no contexto | Tokens médios | Perguntas com referência nova |
|---|---:|---:|---:|
| Só os trechos iniciais | 19 | — | — |
| `parent_rag` | 19 | ~2,3 mil | 0 |
| GraphRAG de 28/10 | 22 | ~6,2 mil | 2 (D008, D020) |
| `graph_rag_v2` de 29/10 | 21 | ~2,9 mil | 2 |
| **GraphRAG revisado** | **23** | **~4,0 mil** | **3 (D008, D014, D020)** |

Os candidatos do grafo revisado contêm 5 referências ausentes dos trechos
iniciais (D008, D014, D017 e duas de D020); o reranker aceita 4. Na versão de
28/10, as referências novas vinham de entidades genéricas (`Setor:Comércio`,
`Territorio:Brasil`) percorridas pela ordem dos IDs. Os limiares foram
escolhidos nessas mesmas 20 perguntas (1,0 · 4 extras: 19; 0,5 · 4: 21;
0,25 · 6: 23), portanto não medem generalização: a confirmação deve vir do
conjunto de teste. Cobertura não é qualidade da resposta; D010, D011, D016 e
D018 continuam sem a referência no contexto.

```powershell
.\.venv\Scripts\python.exe comparacao/avaliacao/cobertura.py openai_rerank_dev_20261028_r1 --versoes parent_rag,graph_rag
.\.venv\Scripts\python.exe comparacao/avaliacao/cobertura.py openai_rerank_dev_20261028_r1 --versoes graph_rag --candidatos
```

### Rodadas de desenvolvimento de 03/11/2026

Rodadas `revisado_dev_20261103_r1..r3` (commit `cac4929`, mesmo perfil, índice e
perguntas das rodadas de 28/10; 180 execuções, sem erros). Marcadores literais, de 34:

| Versão | Rodadas 1 / 2 / 3 | Média | Contexto (mediana) | Recuperação (mediana) | Extras citados |
|---|---|---:|---:|---:|---:|
| RAG simples | 22 / 22 / 22 | 22,0 | ~1,1 mil tokens | 17 s | — |
| `parent_rag` | 23 / 23 / 23 | 23,0 | ~2,4 mil tokens | 17 s | — |
| GraphRAG revisado | 23 / 24 / 24 | 23,7 | ~4,0 mil tokens | 36 s | 12 de 168 |
| GraphRAG de 28/10 | 25 / 24 / 24 | 24,3 | ~6,5 mil tokens | 18 s | 10 de 651 |

- O GraphRAG revisado ganha na D014 (3 de 3 marcadores nas 3 rodadas, contra
  2 na versão de 28/10 e no `parent_rag`): a página 5 da metodologia chega pela
  continuidade entre páginas. D013 também melhora em 2 das 3 rodadas.
- Perde a D010: a versão de 28/10 marcava "dados preliminares" ao citar um valor
  **errado** (1,68% em vez de ~1,59%); a revisada responde que a taxa não está
  nas fontes. Perde a D001: a resposta cita a Secretaria da Fazenda, mas não o
  termo "ICMS" exigido pelo marcador.
- Os trechos do grafo citados nas respostas passam de 1,5% para 7%, quase todos
  da busca por rótulos; o contexto cai ~40%. O reranker dos candidatos dobra o
  tempo de recuperação.
- Marcadores são triagem: a diferença entre as versões (menos de 1 marcador)
  está dentro da variação vista entre rodadas, e a rubrica com revisão humana
  continua necessária. As perguntas são as mesmas usadas para escolher os
  limiares do grafo; a confirmação deve vir do conjunto de teste.

## Ablação e rodadas experimentais

`simple_rag` e `graph_rag` são as versões comparadas, e o `avaliar` roda só essas
duas quando `--versoes` não é informado. `parent_rag` (ablação) é o RAG simples com
os mesmos pais literais do GraphRAG e sem nenhum candidato do grafo: separa o
efeito do contexto maior do efeito do grafo. Usa o mesmo perfil, índice e
ranking inicial.

```powershell
.\.venv\Scripts\python.exe comparacao/run.py avaliar --split desenvolvimento --saida experimental_r1 --versoes parent_rag
.\.venv\Scripts\python.exe comparacao/avaliacao/marcadores.py experimental_r1 --versoes parent_rag
```

### Rodadas experimentais de 29/10/2026

A variante `graph_rag_v2` destas rodadas foi incorporada ao `graph_rag` em
03/11/2026 (veja [GraphRAG revisado](#graphrag-revisado-03112026)); seu código
está no commit `7be2b27`.

Rodadas `experimental_dev_20261029_r1..r3` (mesmo commit-base, perfil e índice
das rodadas congeladas; 120 execuções, sem erros). Marcadores literais, de 34:

| Versão | Rodadas 1 / 2 / 3 | Média | Contexto (mediana) | Recuperação (mediana) |
|---|---|---:|---:|---:|
| RAG simples (congelada, 28/10) | 22 / 21 / 23 | 22,0 | ~1,1 mil tokens | 17 s |
| `parent_rag` | 24 / 23 / 24 | 23,7 | ~2,4 mil tokens | 18 s |
| `graph_rag_v2` | 23 / 24 / 23 | 23,3 | ~2,9 mil tokens | 30 s |
| GraphRAG (congelada, 28/10) | 25 / 24 / 24 | 24,3 | ~6,5 mil tokens | 17 s |

- Os pais literais explicam +1,7 dos +2,3 marcadores do GraphRAG sobre o RAG
  simples (D001 e D014). A diferença restante entre GraphRAG e `parent_rag` está
  na D010: linhas irmãs da Tabela 4.2 levaram a resposta a citar dados
  preliminares, mas com valor errado (1,68% em vez de ~1,59%).
- `graph_rag_v2` reduz o contexto à metade sem perder marcadores fora da D010,
  mas não ganha nenhum; D016 e D017 continuam falhando porque nenhum vizinho do
  grafo supera o limiar do reranker.
- São marcadores automáticos em 20 perguntas, com variação de cerca de 1 marcador
  entre rodadas; não substituem a rubrica nem a revisão humana.

## Preparação e execução

Use **o mesmo ambiente Python** para as duas versões. Na raiz `Graph_Rag`, com
Python 3.13 / Windows x64 para as dependências fixadas:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r graph_rag/requirements.txt
Copy-Item comparacao/.env.example comparacao/.env
```

Preencha `OPENAI_API_KEY` em `comparacao/.env` (ou somente no `.env` da raiz).
Os comandos controlados usam esse arquivo comum. Com `embedding_provider`
`huggingface`, modelos de embeddings ausentes são baixados no primeiro uso.
Para trocar de provedor ou modelo, altere `config.json` e configure a chave
correspondente. Evite roteadores que escolham modelos diferentes a cada chamada.

```powershell
# Extrai e divide o corpus uma única vez e grava os mesmos vetores para ambos.
.\.venv\Scripts\python.exe comparacao/run.py preparar

.\.venv\Scripts\python.exe comparacao/run.py perguntar "Sua pergunta" --versao simple_rag
.\.venv\Scripts\python.exe comparacao/run.py perguntar "Sua pergunta" --versao graph_rag

# Perguntas globais usam comunidades automaticamente no GraphRAG.
.\.venv\Scripts\python.exe comparacao/run.py perguntar "Quais os temas dos documentos?" --versao graph_rag

# Banco de perguntas nas duas versões, numa única sessão.
.\.venv\Scripts\python.exe comparacao/run.py avaliar --split desenvolvimento --saida minha_rodada
.\.venv\Scripts\python.exe comparacao/run.py avaliar --split desenvolvimento --saida minha_rodada --ids D001,D002
```

Cada `perguntar` é um processo novo: carrega o índice e, no GraphRAG, monta o
grafo sobre todos os trechos, o que leva alguns minutos com o corpus completo.
`avaliar` faz isso uma vez e reutiliza índice, modelos e grafo para todas as
perguntas; o grafo é determinístico para o índice e só é lido nas consultas.
Esse carregamento fica fora de `retrieval_seconds` nos dois comandos e aparece
em `session_seconds` no manifesto.

`avaliar` envia somente `pergunta`, alterna a ordem das versões por pergunta e
grava um JSON por execução em `artefatos/resultados/<saida>/`, com
`manifesto.json` (perfil, corpus, hash do banco e cada execução). Repetir o
comando com a mesma `--saida` retoma: mantém execuções gravadas sem erro e refaz
as demais. Retomar com outro perfil, corpus ou banco é recusado.

Os mesmos comandos têm entradas nos aplicativos:

```powershell
.\.venv\Scripts\python.exe simple_rag/rag.py comparar "Sua pergunta"
.\.venv\Scripts\python.exe graph_rag/main.py --comparar "Sua pergunta"
```

O índice comum fica em `comparacao/artefatos/index.json`. O preparo usa a ingestão
e o processamento do GraphRAG para ambos, incluindo tabelas. O comando verifica
hashes dos arquivos e do perfil antes de consultar; mudanças exigem novo preparo.
Ele não substitui os índices Chroma usados pelo aplicativo completo.

## Duas implementações

| Versão | Recuperação e contexto |
|---|---|
| `simple_rag` | Trechos iniciais por similaridade, sem grafo |
| `graph_rag` | Candidatos do grafo (entidades raras, rótulos da tabela ou do documento, título, notas e continuidade, observações da pergunta) escolhidos pelo reranker; pais literais; perguntas globais usam resumos de comunidades |

Existe uma única opção GraphRAG na comparação. Não há seleção de uma versão
reduzida ou uma opção adicional para ativar os recursos completos. Os antigos
nomes `simples`, `grafo` e `grafo_completo` foram removidos: use os nomes das pastas.
O antigo argumento `--comparacao-completa` também foi removido.

O grafo controlado usa regras e entidades cadastradas, sem extração de relações
por LLM. A extração LLM do aplicativo permanece disponível fora desse fluxo.
“GraphRAG” identifica aqui a estratégia do experimento; não significa que todas
as opções da API de produção participem do experimento.

Nos comandos controlados, BM25 e reranking participam apenas da busca inicial
comum descrita acima. Não participam reescrita da pergunta, skills,
calculadoras, HyDE ou enriquecimento LLM da ingestão. Os chats e a API
normais conservam sua arquitetura e permitem configurações locais; **use os
comandos acima para a comparação experimental**, pois alinhar modelos sozinho
não torna esses fluxos equivalentes.

O resultado JSON registra parâmetros, hashes do corpus/perfil, IDs iniciais,
fontes usadas, orçamento estimado e tempos. O tempo de recuperação inclui a
transformação do contexto; no modo global, inclui chamadas para resumos quando
o cache estiver vazio e a consolidação para a pergunta. A preparação do grafo
e o carregamento dos modelos ficam fora desse tempo. A geração mede a síntese
final. Esses tempos não representam o custo total de cada arquitetura.

Registre separadamente execuções com cache frio e quente. Use o mesmo conjunto
de perguntas e gabaritos revisados, repetições e ordem alternada. Temperatura
zero reduz variação, mas não garante respostas idênticas. Para o experimento
final, prefira um identificador de versão fixa do modelo e registre a data.
Resumos são derivados e suas fontes candidatas não comprovam correção das citações.

## Validação local

```powershell
.\.venv\Scripts\python.exe -m pytest comparacao/tests simple_rag/tests -q --capture=sys
```

Os testes simulam os modelos e verificam equivalência da busca inicial, prompt,
orçamento, expansão, processamento global e rejeição de corpus/perfil alterado.
Eles não medem qualidade de respostas reais. Mudanças de provedor ou modelo de
embedding alteram o perfil e exigem novo `preparar`.
