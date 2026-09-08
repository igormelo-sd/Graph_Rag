# Indicadores de conjuntura

## Bases de comparação

- **Variação mensal:** comparar com período imediatamente anterior. Usar série
  dessazonalizada quando a fonte a disponibilizar.
- **Variação interanual:** comparar com mesmo período do ano anterior.
- **Acumulado no ano:** comparar soma ou índice acumulado desde janeiro com
  igual intervalo do ano anterior.
- **Quatro trimestres:** comparar janela móvel de quatro trimestres com janela
  anterior equivalente.

Não combinar taxas construídas com bases diferentes.

## Cálculos

Para níveis compatíveis:

```text
variação (%) = (valor final / valor inicial - 1) × 100
```

Para duas taxas:

```text
diferença (p.p.) = taxa final - taxa inicial
```

Quando pesos setoriais estiverem documentados:

```text
contribuição aproximada (p.p.) = peso inicial × variação setorial (%)
```

Não calcular contribuição quando pesos, cobertura ou método de encadeamento não
estiverem disponíveis.

## Controles conceituais

- **Nível:** tamanho observado do indicador.
- **Taxa:** mudança relativa entre dois níveis.
- **Participação:** parcela de um componente no total.
- **Contribuição:** parcela da mudança total atribuída ao componente.
- **Índice:** medida relativa a uma base, normalmente 100.
- **Valor nominal:** preço corrente do período.
- **Valor real ou volume:** medida descontada de preços conforme método da fonte.

## Erros a evitar

- Chamar alta menor de queda; isso normalmente é desaceleração.
- Chamar queda menor de crescimento; isso normalmente é menor retração.
- Somar taxas de crescimento de setores.
- Inferir causalidade apenas por coincidência temporal.
- Comparar índice com valor monetário.
- Ignorar revisão, sazonalidade ou efeito-base citados nos documentos.
