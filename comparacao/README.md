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
| Corpus | `../graphrag/data` |

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
os 5 resultados iniciais.

## Preparação e execução

Use **o mesmo ambiente Python** para as duas versões. Na raiz `Graph_Rag`, com
Python 3.11 / Windows x64 para as dependências fixadas:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r graphrag/requirements.txt
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

.\.venv\Scripts\python.exe comparacao/run.py perguntar "Sua pergunta" --versao rag_simples
.\.venv\Scripts\python.exe comparacao/run.py perguntar "Sua pergunta" --versao graphrag

# Perguntas globais usam comunidades automaticamente no GraphRAG.
.\.venv\Scripts\python.exe comparacao/run.py perguntar "Quais os temas dos documentos?" --versao graphrag

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
.\.venv\Scripts\python.exe rag_simples/rag.py comparar "Sua pergunta"
.\.venv\Scripts\python.exe graphrag/main.py --comparar "Sua pergunta"
```

O índice comum fica em `comparacao/artefatos/index.json`. O preparo usa a ingestão
e o processamento do GraphRAG para ambos, incluindo tabelas. O comando verifica
hashes dos arquivos e do perfil antes de consultar; mudanças exigem novo preparo.
Ele não substitui os índices Chroma usados pelo aplicativo completo.

## Duas implementações

| Versão | Recuperação e contexto |
|---|---|
| `rag_simples` | Trechos iniciais por similaridade, sem grafo |
| `graphrag` | Expansão por entidades e estrutura, contexto dos documentos; perguntas globais usam resumos de comunidades |

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
.\.venv\Scripts\python.exe -m pytest comparacao/tests rag_simples/tests -q --capture=sys
```

Os testes simulam os modelos e verificam equivalência da busca inicial, prompt,
orçamento, expansão, processamento global e rejeição de corpus/perfil alterado.
Eles não medem qualidade de respostas reais. Mudanças de provedor ou modelo de
embedding alteram o perfil e exigem novo `preparar`.
