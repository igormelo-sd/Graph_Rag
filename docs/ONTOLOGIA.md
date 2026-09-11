# Ontologia — o dicionário do grafo de conhecimento

> Parte da série: [RAG](RAG.md) · [Grafos](GRAFOS.md) · [Ontologia](ONTOLOGIA.md).
> Código: `src/graph_ontology.py`, usado por `src/graph_indexing.py`.

## 1. O que é ontologia, sem jargão

**Ontologia** é a lista oficial de **categorias que o sistema sabe reconhecer**. Se o
grafo é o mapa da biblioteca ([GRAFOS.md](GRAFOS.md)), a ontologia é a **legenda** do
mapa: ela diz quais tipos de ponto existem (cidade, rio, estrada...) — e tudo que não
está na legenda, o cartógrafo simplesmente não desenha.

No projeto: quando o extrator com IA lê um chunk, ele só cria nós das categorias
permitidas (`allowed_entity_types`). Mencionou um município mas `Municipio` não está no
dicionário? Vira texto solto — presente no vetor, invisível para a navegação por relações.

## 2. Os 9 tipos fixos: o essencial dos boletins Seade

Definidos em `_FIXED_TYPES` (`src/graph_ontology.py:19`), escolhidos para o domínio
econômico dos boletins SP Economia:

| Tipo | O que captura | Exemplo |
|---|---|---|
| `Indicador` | métricas e índices | PIB, desemprego, saldo de empregos, IPCA |
| `Setor` | ramos de atividade | indústria de transformação, comércio, construção |
| `Região` | recortes geográficos | Estado de SP, RMSP, interior paulista |
| `Período` | recortes de tempo | 2022, 1T2023, "primeiro trimestre de 2022" |
| `FonteDados` | quem mede/divulga | CAGED, PNAD Contínua, RAIS, SEADE |
| `Tabela` | tabela extraída do PDF | tabela da página 4 do boletim de junho/2022 |
| `Grafico` | gráfico rasterizado | gráfico de barras da página 7 |
| `Pagina` | página (`arquivo#página`) | `SpEconomia-...pdf#p4` |
| `Documento` | o boletim inteiro | `SpEconomia-junho-2022-...pdf` |

Os cinco primeiros formam o vocabulário analítico (o que os economistas cruzam:
indicador × setor × região × período × fonte); os quatro últimos ancoram cada fato no
documento — é por eles que uma tripla sempre pode ser rastreada até a fonte citável.

## 3. A descoberta dinâmica: o dicionário que aprende (opt-in)

Nove categorias não cobrem tudo — e cada corpus tem seus temas recorrentes. Com
`RAG_ONTOLOGY_DISCOVER=1`, o sistema deixa o LLM **propor até 4 categorias novas** a
partir do próprio corpus. O processo (`discover_entity_types`):

1. **Amostra estratégica** — até 6 chunks em posições espalhadas (início, meio, fim:
   índices `[0, 1, mid-1, mid, -2, -1]`), para representar o corpus inteiro sem ler tudo.
2. **Pergunta ao LLM** — o prompt (`_ONTOLOGY_PROMPT`) se apresenta como "especialista
   em ontologia econômica dos boletins SEADE", lista os tipos já existentes (proibido
   repetir) e pede até 4 adicionais, com exemplos úteis (`Empresa`, `Municipio`,
   `PoliticaPublica`, `Produto`, `CadeiaProdutiva`) e proibição de genéricos
   (`Conceito`, `Dado`, `Outro`). Resposta exigida em JSON puro.
3. **Higieniza** — normaliza para PascalCase sem acento/espaço, descarta repetidos e
   nomes fora do tamanho 3–20, corta em 4.
4. **Cacheia** — salva em `graph_store/ontology.json`; nas próximas vezes usa o cache
   (só redescobre com `force` em rebuild). Custo total: **1 chamada LLM por reindexação**.
5. **Falha fechada** — qualquer erro (JSON inválido, timeout, sem amostra) resulta em
   `[]`: o sistema usa só os fixos. A ontologia nunca quebra a indexação.

## 4. Como a ontologia alimenta a extração e a busca

O encadeamento, de ponta a ponta:

```
ontology.json (+ 9 fixos)
  → allowed_entity_types do DynamicLLMPathExtractor
    → triplas extraídas por chunk (máx. 6)
      → nós navegáveis em graph_store.json
        → LLMSynonymRetriever caminha path_depth=2
          → chunks conectados entram no contexto do LLM
```

O efeito prático, com exemplo: suponha que `Municipio` foi descoberto. O chunk *"o
emprego em Campinas cresceu 3% em 2023"* gera `[Emprego] —APLICA_SE_A→ [Campinas]`.
Pergunta: *"onde o emprego mais cresceu no interior?"* — o retriever chega a
`[Campinas]` pelo caminho e traz o chunk, mesmo que "Campinas" nunca apareça na
pergunta. Sem `Municipio` no dicionário, essa ponte não existiria: restaria torcer
para a busca vetorial achar o trecho por similaridade.

Note a divisão de trabalho: a ontologia **não decide relevância** — ela decide
**endereçabilidade**. O que é relevante quem decide é o retriever caminhando; a
ontologia só garante que os conceitos existam como endereço no mapa.

## 5. Quando ativar (e quando não)

- **Ative** (`RAG_ONTOLOGY_DISCOVER=1`) quando o corpus tem temas recorrentes fora dos
  9 fixos — ex.: boletins que citam empresas, municípios ou políticas específicas — e
  as perguntas giram em torno deles.
- **Deixe desligado** (padrão) se as perguntas são as clássicas indicador × setor ×
  região × período: os fixos bastam, e cada tipo extra é mais extração, mais nós e
  mais caminhos — ou seja, mais ruído potencial.
- **Audite** o `ontology.json` após a primeira descoberta: tipos ruins (genéricos ou
  sobrepostos aos fixos) devem ser removidos do cache antes do rebuild.

## 6. Resumo em 5 linhas

1. Ontologia = as categorias que o extrator pode reconhecer (a legenda do mapa).
2. 9 tipos fixos cobrem o núcleo econômico + a âncora documental.
3. A descoberta dinâmica aprende até 4 tipos do próprio corpus (1 chamada LLM, com cache).
4. Só o que está no dicionário vira nó navegável — o resto fica texto solto.
5. Ela não ranqueia nada: torna conceitos *endereçáveis* para o retriever caminhar.
