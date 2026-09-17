# TCC.md — Portando este projeto para um TCC

> Guia prático para transformar o RAG Estatístico SP em Trabalho de Conclusão de Curso
> (Ciência/Engenharia da Computação, Sistemas de Informação ou Economia Computacional).
> Entenda o sistema em [RAG](RAG.md), [GRAFOS](GRAFOS.md), [ONTOLOGIA](ONTOLOGIA.md) e
> nos detalhes técnicos em [PYTHON.md](PYTHON.md).

## 1. Por que este projeto rende um bom TCC

1. **Problema real e delimitável**: responder perguntas econômicas com fontes, em português,
   sobre um corpus fechado (10 boletins Seade) — escopo controlável, sem "resolver a IA geral".
2. **Hipótese testável**: dá para medir se cada peça ajuda (grafo, rerank, BM25, ontologia)
   com experimentos de **ablação** (liga/desliga e compara) — o formato favorito de bancas.
3. **Infra pronta**: pipeline completo + 15 suítes de teste + métricas Prometheus; o aluno foca
   na pergunta científica, não em plumbing.
4. **Contribuição clara**: português econômico é sub-representado na literatura de RAG; qualquer
   medição sistemática aqui é novidade publicável.

## 2. Recortes de tema sugeridos (escolha 1)

| # | Título candidato | Pergunta central | Peças avaliadas |
|---|---|---|---|
| A | *Impacto do grafo de conhecimento na recuperação de contexto em RAG em português* | O grafo melhora recall/resposta? | `--graph` on/off, costura on/off |
| B | *Busca híbrida vs. vetorial pura em documentos econômicos em PT-BR* | BM25+embedding supera cada um isolado? | `build_hybrid_retriever` vs. só-vetor vs. só-BM25 |
| C | *Estratégias de reranking: cross-encoder local vs. LLM vs. score* | Qual reranker entrega mais por custo? | `bge-reranker-v2-m3` × `LLMRerank` × `ScoreReranker` + latência/custo |
| D | *Chunking de tabelas para séries temporais em RAG* | Linha-por-chunk vs. tabela-inteira? | `full_table` × `row_per_chunk`, `RAG_SMALL_TABLE_MAX_ROWS` |
| E | *Ontologia dinâmica na extração de entidades econômicas* | Tipos descobertos melhoram o grafo? | `RAG_ONTOLOGY_DISCOVER` 0/1, qualidade das triplas |
| F | *Validação numérica automática contra alucinação* | O validador pega erros reais? | `validate_numbers`: precisão/recall em respostas com erros injetados |

O recorte **A** é o mais "redondo": usa o diferencial do projeto (grafo) e tem baseline natural.

## 3. Desenho experimental (o coração do TCC)

### 3.1. Dataset de avaliação (a construir — contribuição sua!)

- Monte **50–100 perguntas** sobre os boletins, estratificadas: factuais ("qual o valor de X
  em 2022?"), comparativas ("como evoluiu X entre 2020–2023?"), setoriais, regionais e
  **adversariais** (pergunta fora do corpus → espera-se recusa, não chute).
- Para cada uma, registre **gabarito**: resposta esperada + trechos-fonte (arquivo/página).
  Reaproveite `SourceInfo`/`ValidationInfo` da API como formato.
- Versione como `eval/golden.json` no repo — dataset próprio conta como contribuição.

### 3.2. Métricas (retrieval + geração + custo)

| Nível | Métrica | Como obter |
|---|---|---|
| Retrieval | Recall@k, MRR (fonte certa no top-k?) | Comparar `sources` retornadas vs. gabarito |
| Geração | Faithfulness (resposta ⊆ fontes?), relevância | `validate_numbers`/`validate_citations` + avaliação manual cega; `ragas` já está no `requirements.txt` |
| Robustez | Taxa de recusa correta em adversariais | % de `REFUSAL_TEXT` quando deveria recusar |
| Custo | Latência p50/p95, chamadas LLM, tokens/custo USD | `/metrics` + `QueryDiagnostics` (já instrumentados!) |

### 3.3. Ablações (tabela-modelo de resultados)

| Config | Recall@20 | Faithfulness | Latência p50 | Custo/query |
|---|---|---|---|---|
| Baseline: só vetorial, sem rerank | | | | |
| + BM25 (híbrido) | | | | |
| + rerank BGE | | | | |
| + costura do grafo | | | | |
| + grafo semântico (`--graph`) | | | | |
| + ontologia dinâmica | | | | |

Cada linha é uma flag do `.env` — experimento barato e reproduzível. Teste de significância
simples (ex.: Wilcoxon pareado por pergunta) impressiona bancas sem complicar.

## 4. Estrutura de capítulos sugerida (com o que escrever em cada)

1. **Introdução** — problema (alucinação em QA econômico), objetivos geral/específicos,
   justificativa (PT-BR econômico sub-representado), organização do trabalho.
2. **Fundamentação teórica** — LLMs e alucinação; embeddings e busca vetorial; BM25 e fusão
   (reciprocal rank); RAG; reranking (cross-encoders); grafos de conhecimento/Property Graph;
   ontologias. (Use `docs/` como roteiro, aprofunde com 15–25 referências.)
3. **Trabalhos relacionados** — RAG avaliado (RAGAS), GraphRAG/Microsoft, LightRAG, RAG em
   português; posicione: "este trabalho avalia sistematicamente X em corpus econômico PT-BR".
4. **Metodologia/Desenvolvimento** — arquitetura (diagrama do pipeline), corpus (os 10 boletins),
   cada módulo com decisão justificada (por que bge-m3? por que chunk 1024/200?), dataset golden,
   métricas, protocolo de ablação. Mapeie para `src/`: tabela módulo → função no pipeline.
5. **Resultados** — tabela de ablações + gráficos (latência × qualidade), análise de erros
   (categorizar 20–30 falhas: chunking? retrieval? síntese? validador?), respostas-modelo comentadas.
6. **Conclusão** — hipótese confirmada/refutada em números, limitações (corpus pequeno, 1 domínio,
   LLM proprietário), trabalhos futuros (mais domínios, avaliação humana maior, fine-tuning do reranker).

## 5. Cronograma-modelo (2 semestres)

| Meses | Entrega |
|---|---|
| 1–2 | Fundamentação + ambiente rodando (`--cli` respondendo) |
| 3–4 | Dataset golden v1 (50 perguntas + gabaritos) + harness de avaliação |
| 5–6 | Ablações + análise de erros → qualificação |
| 7–8 | Escrita + replicação final com seed/versões fixadas |

## 6. O que simplificar / isolar no repo do TCC

- **Fork magro**: copie só `main.py`, `src/`, `tests/` relevantes, `data/`, `requirements.txt` —
  remova menções a variantes inexistentes (agentic/raptor/selfrag aparecem em comentários).
- **Reprodutibilidade**: fixe versões (`pip freeze > requirements-lock.txt`), registre
  `RAG_EMBED_MODEL`, modelos LLM e o manifesto do índice no apêndice; rode cada ablação com
  `RAG_INDEX_READ_ONLY=1` para o índice não mudar no meio do experimento.
- **Versão didática**: `rag_simples/` (se existir no repo) serve como "Cap. 4.1 — baseline mínimo".
- **Não inclua**: `.env` com chaves, `chroma_db/`, `graph_store/`, `__pycache__/` (liste no
  `.gitignore`; descreva como regenerar em vez de versionar).

## 7. Riscos e como mitigar (bancas perguntam isso)

| Risco | Mitigação |
|---|---|
| Custo de API (centenas de queries × configs) | Estimar via `/metrics` antes; usar Maritaca leve; rodada final única |
| LLM não-determinístico | `temperature=0.0` (já padrão), repetir amostra 3× e reportar variância |
| Corpus pequeno (10 PDFs) | Assumir como delimitação explícita; generalização = trabalho futuro |
| Vazamento do gabarito no contexto | Golden separado do índice; avaliação cega quando manual |
| Privacidade/dados sensíveis | Embedding local (bge-m3) como argumento de privacidade no texto |

## 8. Originalidade e ética

- **Contribuições reivindicáveis**: dataset golden PT-BR econômico; protocolo de ablação do
  grafo estrutural vs. semântico; medição de custo × qualidade dos rerankers; análise de erros.
- **Citação do código-base**: referencie o repositório de origem na metodologia ("sistema-base
  adaptado de ...") e destaque o que é seu (dataset, experimentos, análise).
- **Uso de IA na escrita**: declare conforme as normas da instituição; IA no objeto de estudo
  (RAG) não dispensa autoria do texto.

## 9. Checklist de defesa

- [ ] Demo ao vivo: 1 pergunta factual + 1 adversarial (recusa) + `/health` e `/metrics` na tela
- [ ] Tabela de ablações com todas as células preenchidas
- [ ] 3 exemplos de erro analisados (de onde veio a falha no pipeline)
- [ ] Reprodutibilidade: colega consegue `pip install` → `--cli` → mesmos números (± variância LLM)
- [ ] Slides: 1 arquitetura, 1 tabela de resultados, 1 análise de erro — resto é detalhe
