# Como funcionam o embedding e o RAG deste projeto — explicação acessível

> Este texto explica, sem jargão, o que o projeto faz por baixo dos panos quando
> você faz uma pergunta. Se você quer rodar o sistema, veja o `README.md`.
> Se quer detalhes de código, veja o `AGENTS.md`.

## A ideia em uma frase

O projeto é um **assistente que responde perguntas sobre os boletins SP Economia (Seade)**
lendo os PDFs de verdade e mostrando **de onde tirou cada informação** —
em vez de "chutar" a resposta de memória.

## A analogia: biblioteca + bibliotecário + redator

Pense assim:

1. **A biblioteca** são os 10 PDFs em `data/` (indústria farmacêutica, automotiva,
   agropecuária, balança comercial etc.).
2. **O bibliotecário** é o sistema de busca: quando você pergunta algo, ele corre
   até as estantes e traz os trechos mais relevantes.
3. **O redator** é o LLM (ex.: `sabia-4` da Maritaca): ele lê só os trechos que o
   bibliotecário trouxe e escreve a resposta final com base neles.
4. **O revisor** confere se os números citados na resposta existem mesmo nos trechos
   (validação numérica).

Essa técnica — *buscar trechos antes de responder* — chama-se **RAG**
(*Retrieval-Augmented Generation*, "geração aumentada por busca").
Ela reduz alucinações, porque o redator só pode usar o que o bibliotecário encontrou.

## As duas fases: preparar a biblioteca e responder perguntas

### Fase 1 — Preparação (indexação, acontece no primeiro boot)

Antes de responder qualquer coisa, o sistema "organiza a biblioteca":

1. **Lê os PDFs** (`src/ingestion.py`): extrai texto, tabelas e gráficos de cada página.
2. **Pica tudo em pedacinhos** (`src/processing.py`): cada pedacinho chama-se *chunk*.
   - Texto corrido: fatias de ~1024 caracteres, com 200 de sobreposição (para não
     cortar uma frase no meio sem contexto).
   - Tabelas pequenas (até 10 linhas): viram 1 chunk só.
   - Tabelas grandes (séries históricas): cada linha vira 1 chunk, no formato
     `Coluna: valor` — por exemplo `Ano: 2023 / Produção: 1,2 bi`.
   - Gráficos/imagens: viram 1 chunk cada (o texto extraído por OCR/visão).
   - Cada chunk ganha etiquetas: arquivo de origem, página, seção, tipo
     (`text`, `table` ou `image`).
3. **Traduz cada chunk para números** — isso é o **embedding** (detalhes abaixo).
4. **Guarda tudo** em `chroma_db/`: os vetores (números) vão para o banco ChromaDB
   (`chroma.sqlite3`) e uma cópia dos textos vai para `bm25_nodes.pkl`
   (usada pela busca por palavras exatas).

Por isso o primeiro boot demora (~20–30 min em CPU): o computador está lendo 10 PDFs,
picando em ~1490 chunks e calculando os números de cada um. Nos boots seguintes,
ele só reprocessa PDFs que mudaram.

### Fase 2 — Hora da pergunta (cada `POST /query` ou pergunta no CLI)

1. **Interpretação** (`src/query_interpreter.py`): um LLM leve lê sua pergunta e decide
   *onde* procurar (texto? tabelas? séries temporais? grafo?) e reescreve a pergunta
   de forma mais buscável. Ex.: *"E a indústria de remédios?"* vira algo como
   *"evolução da indústria farmacêutica no estado de São Paulo"*.
2. **Busca em paralelo** (`src/analysis_engine.py`): vários "bibliotecários
   especializados" procuram ao mesmo tempo — um em textos, um em tabelas, um em
   séries temporais, um em imagens, e opcionalmente um no grafo.
3. **Reordenação (rerank)**: os ~80 candidatos de cada busca são reordenados para
   ficar com os ~20–24 melhores.
4. **Redação**: o LLM principal lê os melhores trechos e escreve a resposta,
   citando as fontes.
5. **Revisão** (`src/numerical_validator.py`): cada número da resposta é procurado
   nos trechos-fonte. O que não for encontrado é sinalizado como não verificado.

## O que é embedding, afinal?

### A ideia central

Computadores não entendem "significado" — eles entendem números. O **embedding** é
a tradução de um texto para uma **lista de números** que captura o *sentido* do texto.

Exemplo simplificado (na prática são 1024 números, aqui mostro 3):

| Trecho | Representação (ilustrativa) |
|---|---|
| "indústria farmacêutica cresceu" | `[0.9, 0.1, 0.2]` |
| "setor de medicamentos avançou" | `[0.85, 0.15, 0.25]` |
| "colheita de soja bateu recorde" | `[0.1, 0.9, 0.1]` |

Note que as duas primeiras frases têm números **parecidos**, embora não compartilhem
quase nenhuma palavra — porque significam quase a mesma coisa. A terceira tem números
**diferentes**, porque fala de outro assunto. Essa "proximidade de significado" é
medida matematicamente (distância do cosseno): quanto mais perto, mais parecido o sentido.

### Como este projeto faz isso

- **Modelo**: `BAAI/bge-m3` (`src/indexing.py:setup_embeddings`). É um modelo aberto
  que roda **na sua própria máquina** — nenhum trecho dos PDFs é enviado para a nuvem
  na hora de vetorizar.
- **Dimensão 1024**: cada chunk vira uma lista de 1024 números. Mais números = mais
  nuances de sentido capturadas.
- **A pergunta também vira números**: na hora da busca, sua pergunta passa pelo mesmo
  modelo e vira uma lista de 1024 números. O sistema então procura os chunks cujos
  números estão mais próximos — ou seja, os trechos com sentido mais parecido.
- **Por que isso é poderoso**: uma busca comum (Ctrl+F) só acha palavras idênticas.
  O embedding acha *ideias*: perguntar "remédios" encontra trechos que falam
  "farmacêutica" e "medicamentos", mesmo sem a palavra "remédios" no texto.

### E o que é o BM25 (a outra metade da busca)?

O embedding é ótimo com sentido, mas às vezes você quer a palavra **exata** —
um ano ("2023"), um município, uma sigla ("PIB"). Para isso existe a busca **BM25**:
ela conta quantas vezes as palavras da pergunta aparecem em cada chunk, dando peso
maior para palavras raras (ex.: "farmacêutica" vale mais que "estado").

Detalhes deste projeto (`src/text_retriever.py:build_hybrid_retriever`):

- O BM25 usa *stemmer* de português: "indústrias", "industrial" e "indústria" são
  tratadas como a mesma raiz — a busca entende flexões do nosso idioma.
- O sistema gera ainda **2 variações da sua pergunta** (query fusion) para ampliar
  a rede — ex.: "indústria farmacêutica SP" + "setor de medicamentos São Paulo".
- Os rankings do embedding e do BM25 são **fundidos** (*reciprocal rank fusion*):
  um chunk que aparece bem nas duas listas sobe para o topo. Sentido + palavra exata,
  o melhor dos dois mundos. É por isso que se chama **busca híbrida**.

## Um exemplo completo, passo a passo

Pergunta: *"A indústria farmacêutica paulista cresceu em 2022?"*

1. **Interpretação**: fontes = texto + tabelas + séries; reescrita =
   *"evolução da indústria farmacêutica no estado de São Paulo em 2022"*.
2. **Embedding da pergunta**: o texto vira 1024 números.
3. **Busca vetorial**: encontra chunks cujo sentido é próximo — inclusive um que diz
   *"o setor de medicamentos registrou expansão"*, sem a palavra "cresceu".
4. **Busca BM25**: encontra chunks com as palavras exatas "farmacêutica" e "2022",
   incluindo linhas de tabela `Ano: 2022 / Variação: +4,1%`.
5. **Fusão + rerank**: o cross-encoder local (`bge-reranker-v2-m3`) relê os candidatos
   com calma e escolhe os ~20 melhores, diversificando entre documentos
   (no máximo 3 chunks por PDF, para não viciar numa fonte só).
6. **Redação**: o LLM escreve *"Sim, cresceu X% em 2022..."* citando o boletim
   `SpEconomia-junho-2022-...pdf`.
7. **Revisão**: o validador procura "X%" no trecho-fonte. Achou? Verificado.
   Não achou? A resposta avisa que o número não foi confirmado.

## O grafo: o mapa que ajuda a recuperar contexto

A busca híbrida (embedding + BM25) já encontra trechos parecidos com a pergunta —
mas ela tem dois pontos cegos, e é aí que o **grafo de conhecimento** entra.
Pense no grafo como o **mapa da biblioteca**: ele não guarda os livros, guarda
**como as coisas se relacionam** — qual indicador pertence a qual setor, em qual
período e região, e qual chunk está ao lado de qual.

### Os dois pontos cegos que o grafo resolve

**1. O contexto partido no meio.** Quando o sistema "pica" o PDF em chunks, uma ideia
pode ficar dividida: o chunk 2 diz *"a indústria farmacêutica..."* e o chunk 3 continua
*"...cresceu 4,1% em 2022"*. A busca pode trazer só o chunk 3 — e o redator recebe um
número sem saber de quê. O grafo costura esses vizinhos de volta (veja "costura" abaixo).

**2. A pergunta que exige pular entre ideias.** *"Quais setores puxaram o emprego no
interior em 2023?"* não é respondida por um chunk isolado: é preciso ligar *setor →
indicador → região → período*. A busca vetorial traz candidatos soltos; o grafo traz
**caminhos** — ele anda pelas ligações e devolve chunks conectados entre si.

### Camada 1 — o mapa estrutural (sempre ligado, custo zero)

Sem usar IA nenhuma, o sistema monta um mapa da estrutura dos documentos a partir das
etiquetas que cada chunk já tem (arquivo, página, `chunk_id`, tipo). É determinístico,
grátis e está sempre ativo (`RAG_GRAPH_STRUCT=1`). As ligações são (`src/graph_indexing.py`):

| Ligação | O que significa | Para que serve |
|---|---|---|
| `CONTIDA_EM` | chunk → página que o contém | Saber de onde veio cada trecho |
| `PERTENCE_A_DOC` | página → boletim (PDF) | Subir do trecho até o documento |
| `NEXT_CHUNK` | chunk → próximo chunk da mesma página | Reconstituir a ordem do texto |
| `SAME_PAGE` | chunk ↔ vizinhos da mesma página | Trazer o entorno imediato |
| `DESCRITA_EM` | tabela/gráfico → texto vizinho (±1 chunk) | Juntar número com sua explicação |

**A costura na prática** (`GraphRetriever.retrieve_neighbors`, usada em
`src/analysis_engine.py`): depois da busca textual, o sistema olha cada chunk
trazido e busca seus vizinhos (chunk anterior e posterior da mesma página).
Exemplo real: a busca trouxe o chunk 3 (*"...cresceu 4,1% em 2022"*) — a costura
anexa o chunk 2 (*"a indústria farmacêutica..."*) e o redator recebe a frase completa.
Para não inundar o contexto, há um orçamento: no máximo ~30% de vizinhos extras
(6 no máximo), sem repetir chunks já presentes.

### Camada 2 — o mapa de significados (extração com IA, opt-in)

No modo com IA (`python main.py --cli --graph`, ou `RAG_GRAPH_EMBED=1`), um LLM lê os
chunks narrativos e extrai **entidades e relações** — no máximo 6 por chunk
(`DynamicLLMPathExtractor` em `src/graph_indexing.py:build_or_load_graph`).
Só texto narrativo participa: tabelas e séries têm pouco contexto relacional e já são
cobertas pelos retrievers próprios.

Entidades reconhecidas: **Indicador** (PIB, desemprego, saldo de empregos),
**Setor** (indústria de transformação, comércio), **Região** (Estado de SP, RMSP,
interior), **Período** (2022, 1T2023), **FonteDados** (CAGED, PNAD, SEADE), além de
**Tabela**, **Grafico**, **Pagina** e **Documento**.

Relações reconhecidas: `CRESCEU_EM` e `RECUOU_EM` (indicador → período/região/setor),
`PERTENCE_A` (indicador → setor), `APLICA_SE_A` (dado → região), `MEDIDO_POR`
(indicador → fonte de dados) e `RELACIONA_COM` (indicador ↔ indicador/setor).

Exemplo do que é extraído de *"o emprego na indústria de transformação do interior
cresceu em 2023, segundo o CAGED"*:

```
[Emprego] —PERTENCE_A→ [Indústria de transformação]
[Emprego] —CRESCEU_EM→ [2023]
[Emprego] —APLICA_SE_A→ [Interior paulista]
[Emprego] —MEDIDO_POR→ [CAGED]
```

O grafo é salvo em `graph_store/graph_store.json` (mais um desenho `graph_store.png`)
e reaproveitado nos próximos boots — só é reconstruído quando os PDFs mudam.

### A ontologia: o dicionário do mapa

Se o grafo é o mapa, a **ontologia** é a *legenda* dele: a lista de categorias que o
extrator tem permissão de reconhecer. É ela que define o que vira um ponto navegável
no mapa — e o que fica como texto solto, invisível para a navegação por relações.

**Os 9 tipos fixos** (`_FIXED_TYPES` em `src/graph_ontology.py`) cobrem o essencial
dos boletins Seade:

| Tipo | Exemplo |
|---|---|
| `Indicador` | PIB, taxa de desocupação, saldo de empregos |
| `Setor` | indústria de transformação, comércio, construção |
| `Região` | Estado de SP, RMSP, interior paulista |
| `Período` | 2022, 1T2023, primeiro trimestre de 2022 |
| `FonteDados` | CAGED, PNAD Contínua, SEADE |
| `Tabela` / `Grafico` | tabela ou gráfico extraído de uma página |
| `Pagina` / `Documento` | página `arquivo#página` e o boletim (PDF) |

**A descoberta dinâmica (opt-in).** Nove categorias não cobrem tudo — e se os boletins
falarem muito de empresas, municípios ou políticas públicas? Com `RAG_ONTOLOGY_DISCOVER=1`,
o sistema mostra até 6 trechos de amostra ao LLM e pede que ele proponha **até 4
categorias novas** (ex.: `Empresa`, `Municipio`, `PoliticaPublica`), com regras
anti-lixo: nada de genéricos como "Conceito" ou "Dado", nome em PascalCase sem acento.
Custa 1 chamada de LLM por reindexação, o resultado fica guardado em
`graph_store/ontology.json`, e se qualquer coisa falhar o sistema simplesmente usa os
9 fixos — nada quebra.

**Por que isso importa na recuperação.** Os tipos viram a lista `allowed_entity_types`
do extrator (`DynamicLLMPathExtractor`): só o que está no dicionário é extraído como
nó. Exemplo concreto: sem `Municipio` no dicionário, as menções a cidades nos boletins
ficam como texto solto — uma pergunta por município depende só da busca vetorial.
Com `Municipio` descoberto, cada cidade vira um nó ligado por `APLICA_SE_A`, e a
pergunta passa a *navegar* pelo mapa (indicador → município → período), alcançando
chunks conectados que a busca por similaridade deixaria escapar.

### Como o grafo recupera contexto na hora da pergunta

Quando o interpretador inclui `"graph"` nas fontes, o `GraphRetriever`
(`src/graph_retriever.py`) age assim:

1. **Expande a pergunta com sinônimos**: um LLM gera até 10 palavras-chave e termos
   relacionados (*`LLMSynonymRetriever`*) — *"emprego"* vira também *"ocupação,
   contratações, CAGED, mercado de trabalho..."*. Isso captura entidades que a pergunta
   original não nomeou.
2. **Caminha até 2 passos** (`path_depth=2`): a partir de cada entidade encontrada, o
   sistema anda pelas ligações — ex.: *Emprego → CRESCEU_EM → 2023 → (outros indicadores
   de 2023)*. Dois passos é o equilíbrio: 1 passo pega pouco, 3+ passos traz ruído.
3. **Devolve os chunks originais** que mencionam essas entidades (`include_text=True`) —
   o redator recebe texto de verdade, não só nomes de nós.
4. **Remove duplicatas**: chunks que os outros retrievers já trouxeram são filtrados
   (`exclude_ids`), para não gastar o contexto do LLM com repetição.
5. **Se falhar, segue o jogo**: qualquer erro no grafo só gera um aviso no log — a
   resposta sai normalmente com as outras fontes.

Resumindo, o grafo ajuda a recuperação de contexto de **três formas**:

1. **Costura** (estrutural, sempre ativa): recompõe ideias partidas pelo chunking,
   anexando vizinhos — mais contexto, zero custo.
2. **Ponte por entidades** (semântica, opt-in): encontra chunks *conectados por
   significado* (mesmo setor, período ou fonte) que a busca por similaridade deixaria
   escapar — essencial em perguntas que cruzam setor × região × período.
3. **Liga tabela ao texto** (`DESCRITA_EM`): quando um número vem de tabela/gráfico,
   o grafo puxa o parágrafo vizinho que o explica — o redator recebe número +
   interpretação juntos.

## Por que tem ainda tabelas, séries e validação?

- **Tabelas e séries** (`src/tables_retriever.py`, `src/timeseries_retriever.py`):
  números em tabelas precisam de tratamento especial (pandas) — não basta ler o texto
  corrido. É assim que o sistema compara anos e calcula variações.
- **Grafo** (`src/graph_indexing.py`, `src/graph_retriever.py`): o mapa de relações
  entre indicadores, setores, regiões e períodos — mais a costura de chunks vizinhos.
  Ver a seção "O grafo" acima para o detalhamento completo.
- **Validação** (`src/numerical_validator.py`, `src/citation_validator.py`):
  LLMs às vezes trocam dígitos. O revisor automático garante que cada número da
  resposta exista de verdade nos trechos citados.
- **Skills de domínio** (`.agents/skills/`): guias de interpretação econômica
  (ex.: mercado de trabalho) que ensinam o redator a analisar como um economista.

## Glossário rápido

| Termo | Em português claro |
|---|---|
| Embedding | Texto traduzido em lista de números que captura o sentido |
| Chunk | Pedacinho de documento (fatia de texto, linha de tabela, gráfico) |
| Vetor | A lista de números de um chunk (aqui, 1024 números) |
| ChromaDB | O "fichário" onde os vetores ficam guardados (`chroma_db/`) |
| BM25 | Busca por palavras exatas, com peso para palavras raras |
| Busca híbrida | Vetor (sentido) + BM25 (palavra exata) combinados |
| Rerank | Reordenar os candidatos para ficar com os melhores |
| RAG | Buscar trechos nos documentos antes de responder |
| LLM | O modelo de linguagem que interpreta e redige (ex.: sabia-4) |
| Alucinação | Quando o LLM inventa um fato; o RAG + validador existem para evitá-la |
| Grafo de conhecimento | Mapa de entidades (setor, indicador, região...) e suas ligações; costura chunks e acha contextos conectados |
| Costura | Anexar chunks vizinhos (anterior/posterior) para recompor ideias partidas pelo chunking |
| Ontologia | O "dicionário" do grafo: as categorias de entidade que o extrator pode reconhecer (9 fixas + até 4 descobertas) |
