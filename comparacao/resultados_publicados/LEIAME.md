# Resultados do teste congelado (rodadas completas, 16-17/11/2026)

Respostas brutas do conjunto de teste (50 perguntas) com o perfil congelado em
`comparacao/avaliacao/congelamento_20261113_gpt54mini.json` (gpt-5.4-mini, text-embedding-3-small).

| Rodada | simple_rag | lexical_rag | graph_rag |
|---|---|---|---|
| r1 | 50/50 | 50/50 | 50/50 |
| r2 | 50/50 | - | 50/50 |
| r3 | 50/50 | - | 50/50 (retomada em 17/11 após interrupção do processo) |

Cópia de `comparacao/artefatos/resultados/v4b_teste_20261113_r*` (pasta ignorada pelo Git). Cada resposta registra o
corpus (arquivo e SHA-256) usado na consulta.

## Análise pareada (`comparar.py`, split teste, referências do gabarito no contexto)

Arquivos: `analise_teste_simple_graph.json` (r1-r3) e `analise_teste_r1_tres.json` (só r1, com lexical_rag).

| Versão | Referências no contexto (de 94) |
|---|---|
| simple_rag | 37 |
| lexical_rag (r1) | 39 |
| graph_rag | 42 |

graph_rag - simple_rag: +5 referências (IC95% 0 a +10); 6 perguntas a favor do graph, 1 contra, 43 empates;
p (teste dos sinais) = 0,125. A diferença vem quase toda da categoria "integração" (+4). Não é significativa
ao nível de 5%. Mede só a presença de referências no contexto, não a qualidade da resposta (isso depende da
avaliação cega, ainda não feita).

## Arquivos desta pasta (gerados por `comparacao/avaliacao/publicar_resultados.py`)

- `perguntas_teste.jsonl`: as 50 perguntas de teste com gabarito.
- `respostas.csv` e `respostas_legiveis.md`: todas as 350 respostas (r1: 3 versões; r2 e r3: 2 versões), com as fontes citadas.
- `arquivos_embedding.csv`: os 20 arquivos de `data/` usados no embedding, com SHA-256 (conferido contra `data/`) e número de
  trechos. Tabelas com exatamente 1.000 trechos foram limitadas a 1.000 linhas na ingestão (limitação documentada em
  `comparacao/README.md`); as linhas além do teto não têm embedding.
- `MANIFESTO.json`: SHA-256 de cada arquivo desta pasta, manifesto do índice e o registro de congelamento.
- `v4b_teste_20261113_r1..r3/`: as respostas brutas em JSON.
- `analise_teste_*.json`: saída de `comparar.py`.

O índice vetorial (`indice/`) não é versionado; reconstrua com `preparar` usando o perfil congelado e sua chave OpenAI.
