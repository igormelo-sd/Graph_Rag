# Revisão dos gabaritos de teste (03/11/2026)

Conferência assistida das 50 perguntas de `teste.jsonl`, antes da revisão humana.
Não substitui a revisão: o campo `revisao_humana` só muda com a decisão do revisor.

## O que foi conferido

- **Integridade literal** (`validar.py`): todos os trechos de PDF, células de XLSX e
  registros de CSV existem no corpus congelado (manifesto de 20 arquivos).
- **Planilhas**: coluna, ano/trimestre e unidade de cada célula citada.
  - T036, T040, T041: `Tabela 3`, linha 106 = 2º trimestre de 2026; colunas O = PIB,
    I = Serviços (total), E = Indústria extrativa mineral; "Em porcentagem", com ajuste sazonal.
  - T042, T045, T074, T079: `Tabela 1` regional, coluna AE = PIB de 2025, "Em R$ bilhões".
  - T070, T096: `Tabela 1` anual, coluna W = 2023, "em milhões de reais"; W12 = "…" (dado não disponível).
- **CSV**: T046 usa `indice_pim_sem_ajuste`; T047, `indice_atividade_comercio_com_ajuste_sazonal`;
  T048, `indice_atividade_servicos_sem_ajuste`, coerentes com as perguntas.
- **PDF da PMC, p. 29** (T071, T085): no varejo, as colunas são mês/mês anterior (OUT–DEZ),
  mês/igual mês (OUT–DEZ), acumulado no ano (JAN-OUT a JAN-DEZ) e 12 meses; dezembro
  com ajuste = -0,4 e acumulado do ano = 1,6, como no gabarito.
- **Metodologia do PIB mensal**: "relação VA/produção constante" (p. 6), atividades
  estimadas de maneira indireta (p. 11), Denton e defasagem de dois anos (p. 12),
  atualização dos pesos a cada PIB anual (p. 8).

Sem divergência de valor, território, período, unidade ou base de comparação nas 50 perguntas.

## Sugestões

| ID | Tipo | Situação | Sugestão |
|---|---|---|---|
| T057 | Cálculo | -2,8 p.p. é calculado, sem `calculo_esperado` | Registrar `{"tipo": "diferenca", "formula": "SP - Brasil", "valor_esperado": "-2.8", "unidade": "p.p.", "tolerancia_absoluta": 0.05}` |
| T059 | Cálculo | 1,7 p.p. é calculado, sem `calculo_esperado` | Registrar `{"tipo": "diferenca", "formula": "PIB - indústria", "valor_esperado": "1.7", "unidade": "p.p.", "tolerancia_absoluta": 0.05}` |
| T061 | Redação | "a metodologia exige ajuste" é mais forte que a fonte | "...o índice mês/mês anterior da metodologia usa séries ajustadas sazonalmente" |
| T078 | Fonte | "revisões podem alterar séries" não cita a p. 8 | Acrescentar a p. 8 da metodologia (atualização dos pesos aplicada ao ano anterior e ao corrente) |
| T085 | Redação | "contém tabela histórica" é vago; "não inferir números estaduais..." é orientação, não fato do corpus | "Seade metodologia explica índices e traz tabelas de pesos e de índices encadeados"; manter a orientação como ponto de comportamento |

Pontos de comportamento (T087, T093–T099 e os itens "não somar"/"não inferir causalidade")
são critérios de resposta, não fatos literais; foram mantidos.

## Decisão

Se a banca exigir teste cego, a decisão final deve ser de uma pessoa que não
participou do ajuste dos sistemas (veja o README desta pasta).
