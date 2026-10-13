# Filtro dos PDFs do corpus

A conferência identificou resultados estatísticos em quatro dos seis PDFs de
`graphrag/data`, uma publicação metodológica com dados históricos e uma publicação
de notas técnicas sem tabelas de resultados de PIB por estado. A pasta `data` da
raiz contém os mesmos seis arquivos, com hashes iguais, e um PDF adicional.

Nenhum arquivo foi removido. O filtro define o uso das fontes na curadoria das
perguntas, sem alterar o corpus do experimento.

| PDF | Páginas | Conteúdo confirmado | Uso na avaliação |
|---|---:|---|---|
| `pib-vol-val_202504caderno.pdf` | 39 | PIB brasileiro, taxas em volume, valores correntes, componentes e tabelas | Resultados numéricos e interpretação. A capa informa out.–dez. de 2025, atualizada em 03/03/2026; o nome do arquivo é enganoso. |
| `pim-pf-br_202512caderno.pdf` | 42 | Produção industrial brasileira, atividades e categorias econômicas | Resultados numéricos e comparações. Separar ajuste sazonal, comparação interanual e acumulados. |
| `pim-pf-regional_202512.pdf` | 76 | Produção industrial por locais, incluindo Estado de São Paulo | Resultados territoriais e comparação SP/Brasil. São Paulo identifica o estado, não o município. |
| `pmc_202512caderno.pdf` | 61 | Volume e receita nominal de vendas, atividades, UFs e taxas | Resultados numéricos e interpretação. Preservar tipo de comércio, variável e base de comparação. |
| `pib_mensal_trimestral_metodologia.pdf` | 20 | Metodologia, fórmulas, fontes, revisões e tabela histórica de estrutura do VA | Conceitos e interpretação; a Tabela 2 tem dados de 2002, 2010, 2015 e 2019–2021. Não é boletim com resultados de 2026. |
| `contas_regionais_2022_notas_tecnicas.pdf` | 22 | Procedimentos, glossário e quadro de mudança de agregações | Apoio metodológico. Não usar como fonte de valores do PIB estadual de 2022. |
| `data/pib_municipal_ed2019.pdf` — adicional da raiz | 94 | PIB municipal paulista de 2002–2016, participações e análises regionais | Contém dados reais, mas está fora de `graphrag/data`, o corpus configurado. Não integra os gabaritos atuais. |

## Exemplos conferidos

Os números de página abaixo são posições físicas no PDF, começando em 1. A
numeração impressa pode ser diferente.

- **PIB nacional, página PDF 5:** Tabela I.1, resultado de 2025: crescimento
  acumulado de 2,3%; quarto trimestre contra terceiro, com ajuste sazonal: 0,1%.
  A página PDF 4 apresenta PIB anual corrente de R$ 12.738,6 bilhões.
- **PIM nacional, página PDF 22:** Tabela 1, indústria geral: -1,2% de dezembro
  frente a novembro de 2025, ajustado; 0,4% contra dezembro de 2024; 0,6% no
  acumulado de janeiro a dezembro.
- **PIM regional, página PDF 15:** Tabela 1, São Paulo: -1,6% na comparação
  mensal ajustada; -3,2% na interanual; -2,2% no acumulado do ano. Brasil: -1,2%,
  0,4% e 0,6%, respectivamente.
- **PMC, página PDF 29:** Tabela 1, volume de vendas do varejo: -0,4% na
  comparação mensal ajustada, 2,3% na interanual e 1,6% no acumulado do ano.
- **Metodologia Seade, página PDF 11:** Tabela 2, estrutura do VA por atividades,
  com unidades e anos explícitos; indústria de transformação: 14,1% em 2021.
- **Notas técnicas SCR, página PDF 9:** Quadro 1 mapeia agregações de atividades;
  não contém uma tabela de valores ou taxas de PIB estaduais. A página PDF 8
  explica a passagem de 18 para 12 atividades e as ressalvas de comparabilidade.
- **PDF municipal adicional, página PDF 5:** tabela de participação no VA e PIB
  estadual em 2002 e 2016. A participação da RM São Paulo no PIB estadual passa
  de 56,4% para 54,4% nesses anos.

## Conferência e limitações

Foi extraído o texto de todas as páginas dos seis PDFs configurados. Foi feita
conferência visual de uma página representativa com tabela ou quadro em cada
um deles, além do PDF adicional, verificando título, unidade, coluna, território,
período e notas. A inspeção visual foi amostral; não equivale a transcrever e
validar cada célula de todas as tabelas dos documentos.

Há páginas sem texto extraível nos cadernos industriais; isso não significa que
o documento inteiro esteja vazio. Datas, números de página e referências
bibliográficas também não bastam para classificar uma página como resultado
estatístico.

A PMC apresenta uma inconsistência interna a revisar: a descrição metodológica
do varejo ampliado na página PDF 6 inclui atacado especializado; a nota (6) da
Tabela 1, na página PDF 29, menciona apenas atividades 1 a 10, embora a atividade
11 apareça na tabela. Evite gabaritos que resolvam essa discrepância sem revisão.

Os gabaritos do banco são candidatos e estão marcados com revisão humana
pendente. Evidência documental confirma presença e localização da informação;
não confirma automaticamente a correção de uma resposta gerada por RAG.
