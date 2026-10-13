# Expansão por entidades, filhos e pais, e busca global

Implementação em `Graph_Rag/graphrag`. As ideias foram adaptadas do
[GraphRAG Pattern Catalog](https://graphrag.com/concepts/intro-to-graphrag/).

## 1. Expansão por entidades

O grafo liga trechos às entidades reconhecidas com `HAS_ENTITY`. As menções
determinísticas incluem indicadores, territórios e setores cadastrados. Entidades
extraídas pelo LLM também são ligadas aos trechos quando suas relações possuem
proveniência registrada.

Após a recuperação inicial, a engine usa até oito trechos como sementes, procura
outros documentos com entidades compartilhadas e percorre relações de domínio
com fonte registrada. A expansão registra os caminhos, elimina duplicatas e
aplica os filtros existentes de período, território e demais dimensões.

Uma menção compartilhada indica conexão temática; não afirma correlação ou causa.
O número de fontes e de arestas visitadas é limitado.

## 2. Filhos indexáveis e pais literais

Na ingestão narrativa, cada documento/página é dividido em blocos maiores,
respeitando frases e parágrafos. Cada bloco é um pai textual. Esses pais são
divididos em filhos menores, que recebem embeddings e participam da busca.

O texto literal do pai fica nos metadados persistidos do filho e é excluído dos
embeddings e prompts do filho. Depois da fusão e do reranking, filhos do mesmo
pai são consolidados no bloco original, preservando arquivo e página. Tabelas e
imagens mantêm seu processamento especializado.

Se um pai exceder o orçamento inteiro de contexto, o filho permanece como
alternativa. O empacotamento pode omitir outros blocos para respeitar seu orçamento.
Os blocos maiores não representam necessariamente uma seção editorial completa;
seu limite é o documento/página extraído e o tamanho configurado.

A divisão usa o `SentenceSplitter` nativo do LlamaIndex com contagem por caracteres.
A versão e o tamanho dos pais fazem parte do fingerprint da ingestão. Índices
anteriores precisam ser sincronizados antes de usar esta recuperação.

## 3. Resumos de comunidades e perguntas globais

O grafo de agrupamento usa entidades e relações de domínio com proveniência.
Coocorrências de entidades em um trecho podem fornecer pesos temáticos; adjacências
de página e de trecho não geram vínculos semânticos nesse agrupamento.

As comunidades são calculadas por modularidade gulosa do NetworkX. Conteúdo sem
entidades reconhecidas recebe grupos de apoio por documento, para também
participar da síntese. Esta versão possui um nível de comunidades; não implementa
a hierarquia Leiden/Louvain do método completo da Microsoft.

O modelo configurado na factory do aplicativo resume cada comunidade a partir
das fontes literais em lotes. Os resumos são interpretações candidatas, com
referências e qualificadores solicitados no prompt. Na consulta global, todas
as comunidades participam de respostas parciais e da consolidação final.
Fontes grandes são divididas entre lotes, sem descartar sua parte final.

O cache `graph_store/community_summaries.json` depende do corpus, relações,
configuração, modelo e versão do processo. Uma falha não substitui um cache
anterior por um cache incompleto. A construção é serializada por instância.
O cancelamento de uma consulta impede novas chamadas ao modelo; uma chamada já
em andamento pode terminar.

## Uso

Com o ambiente e a chave do provedor configurados, na pasta `graphrag`:

```powershell
# Reconstrói o índice conforme o novo fingerprint.
.\.venv\Scripts\python.exe main.py --index-only

# Prepara os resumos antes de atender perguntas; faz chamadas ao LLM.
.\.venv\Scripts\python.exe main.py --prepare-communities

# Consulta interativa. --graph acrescenta extração de relações pelo LLM.
.\.venv\Scripts\python.exe main.py --cli --graph
```

Também é possível perguntar sem preparação prévia: os resumos são construídos
na primeira pergunta global. Para corpus maior, prefira prepará-los antes de
iniciar a API, evitando que a construção ultrapasse o prazo da requisição.

Exemplos de perguntas:

- Local: “O que dizem os boletins sobre a indústria paulista em 2023?”
- Global: “Quais temas e relações econômicas aparecem nos boletins?”
- Global: “Faça uma síntese dos documentos da base de dados.”

O roteador reconhece perguntas globais por expressões de síntese e de corpus;
o LLM de interpretação também pode selecionar a fonte `global`. A resposta HTTP
preserva fontes literais em `sources` e adiciona dados da busca global em
`knowledge.global_search`, incluindo quantidade de comunidades, trechos e
participação de todas as comunidades. Isso não comprova correção semântica.

## Configuração

| Variável | Padrão | Papel |
|---|---|---|
| `RAG_ENTITY_EXPANSION` | `1` | Expansão da busca inicial por entidades |
| `RAG_ENTITY_CONTEXT_LIMIT` | `8` | Máximo de trechos adicionais por expansão |
| `RAG_ENTITY_CONTEXT_DEPTH` | `1` | Saltos entre entidades; limite de 2 |
| `RAG_PARENT_CONTEXT` | `1` | Recuperação dos pais na síntese local |
| `RAG_PARENT_SIZE` | `3200` | Tamanho dos blocos maiores em caracteres |
| `RAG_GLOBAL_SEARCH` | `1` | Comunidades e roteamento global |
| `RAG_COMMUNITY_SUMMARY_CHARS` | `1800` | Limite dos resumos e das respostas globais intermediárias/final |
| `RAG_MAX_CONTEXT_TOKENS` | `12000` | Orçamento estimado de contexto por chamada |

O tamanho dos filhos continua em `RAG_CHUNK_SIZE`, com sobreposição em
`RAG_CHUNK_OVERLAP`. O limite dos resumos pode ser reduzido automaticamente para
caber no orçamento. Saídas vazias ou que ultrapassem o limite são rejeitadas.

## Verificação

`tests/test_graph_patterns.py` cobre expansão entre documentos, filtragem de
períodos, caminhos de relações, ingestão de filhos, recuperação dos pais,
fingerprints, cobertura das comunidades, cache, falhas, cancelamento,
roteamento e contrato HTTP. Os modelos são simulados nesses testes.

Não houve indexação real do corpus nem avaliação da qualidade das respostas
com o provedor nesta implementação.

Verificação em 8 out. 2026: 40 testes dos padrões e regressões relacionadas
passaram. A execução mais ampla encontrou duas falhas também reproduzidas no
projeto original (mock de domínio incompleto e contrato de citação numérica),
além de erros de acesso a arquivos temporários de testes de índice no Windows.
A suíte completa, portanto, não foi aprovada integralmente.
