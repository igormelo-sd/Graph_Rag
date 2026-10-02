# RAG — Geração Aumentada por Busca (como funciona neste projeto)

> Parte da série: [RAG](RAG.md) · [Grafos](GRAFOS.md) · [Ontologia](ONTOLOGIA.md).
> Versão curta e acessível: `../COMO_FUNCIONA.md`. Para rodar: `../README.md`.

## 1. O que é RAG, em uma frase

**RAG** (*Retrieval-Augmented Generation*) é a técnica de **buscar trechos nos
documentos antes de responder**: em vez de pedir ao LLM que responda de memória
(arriscando inventar fatos), o sistema primeiro recupera os trechos relevantes e
manda o LLM responder **só com base neles**.

## 2. Por que o RAG existe: o problema da alucinação

Um LLM puro funciona como uma pessoa que leu a internet inteira há meses e tenta
responder de cabeça: ela acerta o geral, mas **troca dígitos, datas e nomes** —
isso se chama **alucinação**. Em economia (PIB, taxas, saldos), um dígito errado é
uma resposta errada.

O RAG troca "responder de cabeça" por "responder com os documentos abertos na mesa":
a resposta vem acompanhada das **fontes** (arquivo, página, trecho), e um revisor
automático confere cada número citado. Alucinar continua possível, mas fica muito
mais difícil — e, quando acontece, fica visível.

## 3. A analogia completa: biblioteca, bibliotecários, redator e revisor

| Papel | Quem é no projeto | O que faz |
|---|---|---|
| A biblioteca | `data/` (10 PDFs Seade) + `chroma_db/` (índice) | Onde o conhecimento mora |
| Os bibliotecários | Retrievers (`text`, `tables`, `timeseries`, `images`, `graph`) | Acham os trechos relevantes |
| O chefe dos bibliotecários | `query_interpreter.py` | Decide *onde* procurar e reescreve a pergunta |
| O redator | LLM principal (GPT por padrão) | Escreve a resposta só com os trechos |
| O revisor | `numerical_validator.py` + `citation_validator.py` | Confere números e citações contra as fontes |

## 4. Fase 1 — Preparação: organizando a biblioteca (indexação)

Acontece no primeiro boot (`src/startup.py:initialize`). Depois, só o que mudou é
reprocessado (detecção por data de modificação em `src/index_sync.py`).

### 4.1. Leitura (`src/ingestion.py`)

Extrai de cada PDF: **texto** corrido, **tabelas** e **gráficos** (via OCR/visão),
sempre anotando arquivo e página de origem — a proveniência que permite citar fontes.

### 4.2. Chunking: picando em pedacinhos (`src/processing.py`)

LLMs têm limite de quanto texto leem por vez, e buscar um PDF inteiro seria
impreciso. Por isso tudo é cortado em **chunks**:

- **Texto**: fatias de ~1024 caracteres com 200 de sobreposição (`RAG_CHUNK_SIZE` /
  `RAG_CHUNK_OVERLAP`) — a sobreposição evita que uma ideia morra exatamente no corte.
  Opcionalmente, um LLM leve adiciona título e palavras-chave a cada chunk.
- **Tabelas pequenas** (até 10 linhas, `RAG_SMALL_TABLE_MAX_ROWS`): 1 chunk só.
- **Tabelas grandes** (séries históricas): cada linha vira 1 chunk no formato
  `Coluna: valor` — ex.: `Ano: 2023 / Variação: +4,1% / Fonte: boletim.pdf`.
- **Gráficos**: 1 chunk cada, com o texto extraído por visão.
- Todo chunk ganha etiquetas: `source_file`, `page`, `chunk_id`, `type`
  (`text` / `table` / `image`), seção — e um id determinístico (sha256), para
  reindexações não duplicarem nada.

A quantidade de chunks depende do corpus e da configuração; valores históricos não são garantias para o pipeline atual.

### 4.3. Embedding: traduzindo para números (`src/indexing.py:setup_embeddings`)

Cada chunk passa pelo modelo **`BAAI/bge-m3`**, que o converte numa lista de
**1024 números** (o vetor) capturando o *sentido* do texto. É 100% local: nenhum
trecho vai para a nuvem nessa etapa. Textos de sentido parecido ganham vetores
próximos — *"remédios"* encontra *"farmacêutica"* mesmo sem palavras em comum.

### 4.4. Guarda: o fichário duplo (`chroma_db/`)

- **`chroma.sqlite3`**: os vetores, no banco ChromaDB (busca por proximidade de sentido).
- **`bm25_nodes.pkl`**: os textos originais, para a busca por palavras exatas.
- **`indexed_manifest.json`**: o carimbo do que foi indexado (modelo, dimensão, arquivos).

O primeiro boot prepara os embeddings e o índice; não há tempo medido para esta versão. Depois da preparação, `RAG_INDEX_READ_ONLY=1` evita sincronizações.

## 5. Fase 2 — A pergunta: do texto à resposta

Fluxo de cada `POST /query` (ou pergunta no `--cli`), em `src/analysis_engine.py`:

### 5.1. Interpretação (`src/query_interpreter.py`)

Um LLM leve lê a pergunta e devolve três coisas:

- **`sources`**: onde procurar — `text`, `tables`, `timeseries`, `image`, `graph`.
- **`rewritten_query`**: a pergunta reescrita de forma mais buscável
  (ex.: *"E os remédios?"* → *"evolução da indústria farmacêutica em São Paulo"*).
- **`is_labor_market`**: se é tema de mercado de trabalho (liga a skill de domínio).

### 5.2. Busca em paralelo (os bibliotecários correm juntos)

Cada retriever especializado busca ao mesmo tempo, cada um do seu jeito:

- **Texto** (`text_retriever.py`): busca **híbrida** — embedding (sentido) + BM25
  (palavras exatas, com stemmer de português: *indústria/industriais* = mesma raiz)
  fundidos por *reciprocal rank*. Inclui a consulta original e uma alternativa (query fusion)
  para ampliar a rede. Traz ~80 candidatos.
- **Tabelas / séries** (`tables_retriever.py`, `timeseries_retriever.py`): busca +
  planos JSON e operações Decimal — comparam células, calculam variações e montam gráficos.
- **Imagens** (`images_retriever.py`): busca nos chunks de gráficos.
- **Grafo** (`graph_retriever.py`): navega pelas relações (detalhes em [GRAFOS.md](GRAFOS.md)).

### 5.3. Rerank: a segunda leitura com calma

Os ~80 candidatos passam por um reordenador que escolhe os ~20–24 melhores:

1. **Cross-encoder local** `bge-reranker-v2-m3` (`RAG_BGE_RERANK=1`, padrão) — lê
   pergunta + trecho juntos e dá nota fina. Executado localmente; sua qualidade e latência precisam ser medidas neste corpus.
2. Fallback **LLM rerank** (`LLMRerank`) ou **score híbrido** (`ScoreReranker`, ex.:
   no modo Ollama local, para não estourar a janela do modelo).

Ainda há diversificação: preferência por até três chunks por documento, podendo preencher o limite final com excedentes, para a resposta não
viciar numa fonte só — e a **costura do grafo** anexa chunks vizinhos de ideias
partidas pelo chunking.

### 5.4. Síntese: o redator escreve (1 chamada LLM)

O LLM principal recebe contexto identificado por `[Fonte: arquivo, p./aba ...]`, dados de tabelas e vizinhos, além do bloco da skill. O prompt pede citações inline quando solicitadas; a API retorna fontes e candidatos de evidência separadamente. Se o contexto vier vazio, o sistema **se recusa** a
responder em vez de inventar (`REFUSAL_TEXT`).

### 5.5. Revisão: o revisor confere (`numerical_validator.py`)

Cada ocorrência numérica é comparada ao contexto dos trechos-fonte, considerando indicador, período, região e unidade. Isso é uma heurística, não prova semântica. O resultado vai em `validation`:
`verified/total/unverified` — números não confirmados são sinalizados, não escondidos.
`citation_validator.py` verifica citações explícitas como `(Fonte: arquivo, p. X)`. `claim_evidence` e `calculations` preservam candidatos e contas para revisão; nenhum Python gerado pelo LLM é executado nos cálculos atuais.

## 6. Exemplo didático (valores e resultado ilustrativos)

Pergunta: *"A indústria farmacêutica paulista cresceu em 2022?"*

1. Interpretação → fontes `text+tables+timeseries`, reescrita *"evolução da indústria
   farmacêutica no estado de São Paulo em 2022"*.
2. Vetorial acha *"o setor de medicamentos registrou expansão"* (sentido, sem a
   palavra "cresceu"); BM25 acha `Ano: 2022 / Variação: +4,1%` (palavra exata).
3. Rerank elege os ~20 melhores; a costura anexa o chunk vizinho com o sujeito da frase.
4. O LLM escreve *"Sim, cresceu 4,1%..."* citando `SpEconomia-junho-2022-...pdf`.
5. O revisor compara a ocorrência de "4,1%" e suas dimensões no trecho-fonte → correspondência contextual ou revisão.

## 7. Quando o RAG não basta (limites honestos)

- **Pergunta fora dos documentos** → contexto vazio gera recusa; contexto recuperado insuficiente ainda pode produzir erros.
- **Contexto partido** → mitigado pela costura do grafo, mas chunking sempre perde algo.
- **Números em imagem escaneada mal** → OCR erra, o erro propaga.
- **Custo** → BGE é local; interpretação, síntese e outras etapas podem usar LLM remoto. Uso incompleto ou tarifa ausente implica custo indisponível, não zero.

## 8. Glossário

| Termo | Significado |
|---|---|
| RAG | Buscar trechos antes de responder |
| Chunk | Pedacinho de documento (fatia de texto, linha de tabela, gráfico) |
| Embedding / vetor | Texto convertido em lista de 1024 números que captura o sentido |
| BM25 | Busca por palavras exatas, pesando palavras raras |
| Busca híbrida | Vetor (sentido) + BM25 (palavra exata) fundidos |
| Query fusion | Gerar variações da pergunta para ampliar a busca |
| Rerank | Reordenar candidatos e ficar com os melhores |
| Alucinação | LLM inventando fatos; RAG + validador existem para contê-la |
| REFUSAL_TEXT | Recusa padrão quando não há contexto — melhor que inventar |

Veja [Confiabilidade](CONFIABILIDADE.md) para limitações e avaliação pendente. Nenhum teste ou avaliação foi executado nesta atualização.
