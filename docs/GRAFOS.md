# Grafos de conhecimento — o mapa que ajuda o RAG a recuperar contexto

> Parte da série: [RAG](RAG.md) · [Grafos](GRAFOS.md) · [Ontologia](ONTOLOGIA.md).
> Versão curta: `../COMO_FUNCIONA.md` (seção "O grafo").

## 1. O que é um grafo de conhecimento, em linguagem simples

Um grafo é um **mapa de coisas ligadas**: pontos (**nós**) conectados por setas
nomeadas (**arestas**). Cada fato é uma **tripla** — *sujeito → relação → objeto*:

```
[Emprego] —CRESCEU_EM→ [2023]
[Emprego] —PERTENCE_A→ [Indústria de transformação]
```

Se a busca vetorial é "achar trechos parecidos com a pergunta", o grafo é "achar
trechos **ligados entre si**". Os dois se complementam — por isso o grafo é a 4ª/5ª
fonte do `AnalysisEngine`, não um substituto.

Neste projeto o grafo vive em `graph_store/graph_store.json` (+ um desenho
`graph_store.png`), construído por `src/graph_indexing.py` e consultado por
`src/graph_retriever.py`.

## 2. Por que o RAG precisa do mapa: os dois pontos cegos

**Ponto cego 1 — o contexto partido no meio.** O chunking corta o texto em fatias, e
uma ideia pode ficar dividida: o chunk 2 diz *"a indústria farmacêutica..."* e o
chunk 3 continua *"...cresceu 4,1% em 2022"*. A busca pode trazer só o chunk 3 — um
número sem dono. O grafo sabe que 2 e 3 são vizinhos e **costura** a frase de volta.

**Ponto cego 2 — perguntas que exigem pular entre ideias.** *"Quais setores puxaram o
emprego no interior em 2023?"* cruza setor × indicador × região × período — nenhum
chunk isolado responde. A busca vetorial traz candidatos soltos; o grafo **caminha
pelas ligações** e devolve chunks conectados pelo mesmo caminho.

## 3. Camada 1 — o mapa estrutural (sempre ligado, custo zero)

Sem nenhuma IA, o sistema desenha o mapa da **estrutura dos documentos** a partir das
etiquetas que cada chunk já tem (`source_file`, `page`, `chunk_id`, `type`). É
determinístico, grátis e ativo por padrão (`RAG_GRAPH_STRUCT=1`). Código:
`_inject_structural_triplets` em `src/graph_indexing.py`.

| Aresta | Liga chunk/página a... | Para que serve |
|---|---|---|
| `CONTIDA_EM` | chunk → página | Saber de onde veio cada trecho |
| `PERTENCE_A_DOC` | página → boletim (PDF) | Subir do trecho até o documento |
| `NEXT_CHUNK` | chunk → próximo chunk da mesma página | Reconstituir a ordem do texto |
| `SAME_PAGE` | chunk ↔ vizinhos (±1) da mesma página | Trazer o entorno imediato |
| `DESCRITA_EM` | tabela/gráfico → texto vizinho (±1) | Juntar o número com sua explicação |

### 3.1. A costura na prática (`retrieve_neighbors`)

Depois da busca textual, o `AnalysisEngine` pede ao grafo os vizinhos de cada chunk
trazido (anterior e posterior da mesma página) e os anexa ao contexto — com orçamento:
**no máximo ~30% de extras (6 no máximo)** e sem repetir o que já veio. É assim que o
redator recebe *"a indústria farmacêutica... cresceu 4,1%"* em vez de *"...cresceu 4,1%"*
sem sujeito. Falhou? Só loga um aviso e segue — a costura nunca quebra a resposta.

## 4. Camada 2 — o mapa de significados (extração com IA, opt-in)

Liga-se com `python main.py --cli --graph` ou `RAG_GRAPH_EMBED=1`. Um LLM lê os chunks
**narrativos** (tabelas/séries têm pouco contexto relacional e já têm retrievers
próprios) e extrai até **6 triplas por chunk** (`DynamicLLMPathExtractor` em
`build_or_load_graph`).

### 4.1. As peças do mapa: entidades e relações

As categorias vêm da [ontologia](ONTOLOGIA.md): 9 tipos fixos (`Indicador`, `Setor`,
`Região`, `Período`, `FonteDados`, `Tabela`, `Grafico`, `Pagina`, `Documento`) mais até
4 descobertos dinamicamente. As relações:

| Relação | Lê-se como | Exemplo |
|---|---|---|
| `CRESCEU_EM` | indicador cresceu em... | `[Emprego] —CRESCEU_EM→ [2023]` |
| `RECUOU_EM` | indicador recuou em... | `[Desemprego] —RECUOU_EM→ [RMSP]` |
| `PERTENCE_A` | pertence ao setor/categoria... | `[Emprego] —PERTENCE_A→ [Indústria]` |
| `APLICA_SE_A` | vale para a região... | `[Dado] —APLICA_SE_A→ [Interior]` |
| `MEDIDO_POR` | medido/divulgado por... | `[Emprego] —MEDIDO_POR→ [CAGED]` |
| `RELACIONA_COM` | relaciona-se com... | `[PIB] —RELACIONA_COM→ [Indústria]` |

Exemplo completo, de *"o emprego na indústria de transformação do interior cresceu em
2023, segundo o CAGED"*:

```
[Emprego] —PERTENCE_A→ [Indústria de transformação]
[Emprego] —CRESCEU_EM→ [2023]
[Emprego] —APLICA_SE_A→ [Interior paulista]
[Emprego] —MEDIDO_POR→ [CAGED]
```

### 4.2. Construção, cache e persistência

- **Primeira vez**: extrai de todos os chunks narrativos (lento, consome LLM) e salva
  em `graph_store/graph_store.json` (+ `graph_store.png` visualizável).
- **Próximas vezes**: carrega do disco; as arestas estruturais são reinjetadas
  (idempotentes) sobre o cache.
- **Mudou PDF**: `force_rebuild=True` reconstrói automaticamente.
- **Sem crédito de LLM**: cai para o grafo estrutural (fallback em `build_or_load_graph`).

## 5. Como o grafo recupera contexto na hora da pergunta

Quando o interpretador inclui `"graph"` nas fontes, o `GraphRetriever`
(`src/graph_retriever.py`, via `LLMSynonymRetriever`) faz:

1. **Expande com sinônimos** — o LLM gera até 10 palavras-chave/termos relacionados
   (`max_keywords=10`): *"emprego"* vira *"ocupação, contratações, CAGED, mercado de
   trabalho..."*, capturando entidades que a pergunta nem nomeou.
2. **Caminha até 2 passos** (`path_depth=2`) — de cada entidade encontrada, anda pelas
   ligações (ex.: *Emprego → CRESCEU_EM → 2023 → outros indicadores de 2023*). Dois
   passos é o equilíbrio: 1 pega pouco, 3+ traz ruído.
3. **Devolve os chunks originais** (`include_text=True`) — o redator recebe texto de
   verdade, não só nomes de nós.
4. **Dedup contra os outros retrievers** (`exclude_ids`) — não gasta contexto do LLM
   com repetição.
5. **Falha graciosa** — qualquer erro vira aviso no log; a resposta sai com as demais fontes.

## 6. Resumo: as 3 ajudas do grafo ao RAG

1. **Costura** (estrutural, sempre ativa): recompõe ideias partidas pelo chunking.
2. **Ponte por entidades** (semântica, opt-in): acha chunks conectados por significado
   (mesmo setor/período/fonte) que a similaridade deixaria escapar.
3. **Número + explicação** (`DESCRITA_EM`): quando o dado vem de tabela/gráfico, puxa o
   parágrafo vizinho que o interpreta.

## 7. Flags e modos (referência rápida)

| Config | Padrão | Efeito |
|---|---|---|
| `RAG_GRAPH_STRUCT` | `1` | Mapa estrutural + costura (sempre) |
| `--graph` / `RAG_USE_GRAPH` | desligado | Extração de entidades/relações via LLM |
| `RAG_GRAPH_EMBED` | `0` | Vetoriza também os nós do grafo (2º embedding) |
| `RAG_ONTOLOGY_DISCOVER` | `0` | Descobre até 4 tipos novos de entidade ([ONTOLOGIA.md](ONTOLOGIA.md)) |
