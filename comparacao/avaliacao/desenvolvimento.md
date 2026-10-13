# Perguntas de desenvolvimento

Gabaritos candidatos. Revisão humana pendente.

## D001 — factual

Qual fonte é usada para o índice de valor de impostos líquidos de subsídios no PIB mensal paulista?

**Resposta esperada:** Arrecadação de ICMS da Secretaria da Fazenda e Planejamento do Estado de São Paulo.

**Fontes:**
- pib_mensal_trimestral_metodologia.pdf — página PDF 19

## D002 — factual

Qual proxy de volume é usada para atividades imobiliárias na metodologia paulista?

**Resposta esperada:** Número de consumidores residenciais de energia, como proxy do número de domicílios.

**Fontes:**
- pib_mensal_trimestral_metodologia.pdf — página PDF 18

## D003 — factual

Em que trimestre de cada ano a metodologia paulista prevê incorporar novas ponderações das Contas Regionais?

**Resposta esperada:** No terceiro trimestre.

**Fontes:**
- pib_mensal_trimestral_metodologia.pdf — página PDF 13

## D004 — factual

Qual é a descrição da classe CNAE 47.32-6?

**Resposta esperada:** Comércio varejista de lubrificantes.

**Fontes:**
- cnae20.csv — linha 416

## D005 — factual

Qual o Departamento Regional de Saúde associado a Campinas no cadastro territorial?

**Resposta esperada:** DRS Campinas.

**Fontes:**
- codigos_municipios_regioes.csv — linha 112

## D006 — numerica

Qual foi a variação dos bens de capital no Brasil entre novembro e dezembro de 2025, com ajuste sazonal?

**Resposta esperada:** -8,3%.

**Fontes:**
- pim-pf-br_202512caderno.pdf — página PDF 22

## D007 — numerica

Qual foi a variação da indústria do Rio de Janeiro entre novembro e dezembro de 2025, com ajuste sazonal?

**Resposta esperada:** 2,3%.

**Fontes:**
- pim-pf-regional_202512.pdf — página PDF 15

## D008 — numerica

Qual foi a variação do volume de vendas de equipamentos e materiais para escritório, informática e comunicação no Brasil em dezembro de 2025 frente a dezembro de 2024?

**Resposta esperada:** 31,1%.

**Fontes:**
- pmc_202512caderno.pdf — página PDF 29

## D009 — numerica

Qual foi o PIB brasileiro em valores correntes no quarto trimestre de 2025, em bilhões de reais?

**Resposta esperada:** R$ 3.277,8 bilhões.

**Fontes:**
- pib-vol-val_202504caderno.pdf — página PDF 4

## D010 — numerica

Quanto o PIB paulista variou no primeiro trimestre de 2026 frente ao quarto de 2025, com ajuste sazonal?

**Resposta esperada:** 1,59% aproximadamente; dados preliminares.

**Fontes:**
- tabelas-relatorio-2-trim2026-site.xlsx — Tabela 3!O105
- tabelas-relatorio-2-trim2026-site.xlsx — Tabela 3!A109

## D011 — integracao

Relacione o código IBGE de Adamantina no cadastro territorial ao seu PIB de 2018.

**Resposta esperada:** Código IBGE 3500105 em ambas as bases; PIB de 2018: R$ 1.070.909.946.

**Fontes:**
- codigos_municipios_regioes.csv — linha 4
- pib_municipal_2002_2020.csv — linha 38057

## D012 — integracao

A variação de dezembro de 2025 do varejo brasileiro foi igual no conceito restrito e no ampliado?

**Resposta esperada:** Não: -0,4% no varejo e -1,2% no ampliado, ambos contra novembro e com ajuste sazonal.

**Fontes:**
- pmc_202512caderno.pdf — página PDF 17

## D013 — integracao

Relacione a classe CNAE 47.71-7 ao agrupamento de artigos farmacêuticos da PMC.

**Resposta esperada:** A classe corresponde ao comércio varejista de produtos farmacêuticos para uso humano e veterinário; a PMC inclui 4771-7 no agrupamento farmacêutico, médico, ortopédico e de perfumaria.

**Fontes:**
- cnae20.csv — linha 432
- pmc_202512caderno.pdf — página PDF 5

## D014 — integracao

Como a definição de Valor Adicionado ajuda a evitar confundir produção bruta com PIB?

**Resposta esperada:** VA desconta consumo intermediário da produção; PIB acrescenta impostos líquidos de subsídios ao VA, evitando somar novamente insumos.

**Fontes:**
- pib_mensal_trimestral_metodologia.pdf — página PDF 5
- dicvar_pib_municipal_2002_2020.csv — linha 8

## D015 — sintese

Resuma os instrumentos para reduzir distorções sazonais e alinhar o PIB trimestral às contas anuais.

**Resposta esperada:** X-13 para sazonalidade; benchmarking/Denton para alinhamento anual; objetivos distintos dos dois ajustes.

**Fontes:**
- pib_mensal_trimestral_metodologia.pdf — página PDF 12
- pib_mensal_trimestral_metodologia.pdf — página PDF 13

## D016 — sintese

Quais fontes do corpus permitem distinguir classificação de atividades e classificação territorial?

**Resposta esperada:** CNAE: seção, divisão, grupo e classe; cadastro territorial: município, RA, RM e saúde; código CNAE e código IBGE têm funções diferentes.

**Fontes:**
- dicvar_cnae20.csv — linha 2
- dicvar_cnae20.csv — linha 8
- codigos_municipios_regioes.csv — linha 546

## D017 — sintese

Faça uma síntese das restrições ao usar valores nominais e séries encadeadas para acompanhar crescimento.

**Resposta esperada:** nominal inclui preços; volume permite separar mudança de preços; não aditividade dos componentes encadeados.

**Fontes:**
- pib_mensal_trimestral_metodologia.pdf — página PDF 5
- pib_mensal_trimestral_metodologia.pdf — página PDF 6
- pib_mensal_trimestral_metodologia.pdf — página PDF 7

## D018 — limites

Qual foi o PIB de Adamantina em 2028?

**Resposta esperada:** O corpus não fornece PIB municipal de 2028; não extrapolar a base de 2002–2020.

**Fontes:**
- pib_municipal_2002_2020.csv — linha 36767

## D019 — limites

Qual foi o crescimento dos serviços?

**Resposta esperada:** Pedir território, período, segmento e base de comparação.

**Fontes:**
- dic_variaveis_pms.csv — linha 4
- dic_variaveis_pms.csv — linha 5

## D020 — limites

O crescimento da indústria do Rio de Janeiro em dezembro de 2025 prova que todas as empresas locais cresceram?

**Resposta esperada:** Não. O indicador agregado não comprova comportamento de cada empresa.

**Fontes:**
- pim-pf-regional_202512.pdf — página PDF 15
- pim-pf-br_202512caderno.pdf — página PDF 5
