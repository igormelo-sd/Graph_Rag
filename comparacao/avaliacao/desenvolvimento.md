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

**Pontos obrigatórios:**
- Número de consumidores residenciais de energia.
- Usado como indicador (proxy) da evolução do número de domicílios.

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

**Pontos obrigatórios:**
- Variação de aproximadamente 1,59%.
- Os dados são preliminares e sujeitos a revisão.

**Fontes:**
- tabelas-relatorio-2-trim2026-site.xlsx — Tabela 3!O105
- tabelas-relatorio-2-trim2026-site.xlsx — Tabela 3!A109

## D011 — integracao

Relacione o código IBGE de Adamantina no cadastro territorial ao seu PIB de 2018.

**Resposta esperada:** Código IBGE 3500105 em ambas as bases; PIB de 2018: R$ 1.070.909.946.

**Pontos obrigatórios:**
- Código IBGE de Adamantina: 3500105, o mesmo nas duas bases.
- PIB de Adamantina em 2018: R$ 1.070.909.946.

**Fontes:**
- codigos_municipios_regioes.csv — linha 4
- pib_municipal_2002_2020.csv — linha 38057

**Limitação de indexação:** A comparação controlada indexa só as primeiras 1.000 linhas de cada tabela. A linha citada no gabarito não recebe embedding; analise esta pergunta separadamente.

## D012 — integracao

A variação de dezembro de 2025 do varejo brasileiro, frente a novembro e com ajuste sazonal, foi igual no conceito restrito e no ampliado?

**Resposta esperada:** Não: -0,4% no varejo e -1,2% no ampliado, ambos contra novembro e com ajuste sazonal.

**Pontos obrigatórios:**
- Não, as variações foram diferentes.
- Varejo (conceito restrito): -0,4%.
- Varejo ampliado: -1,2%.
- Ambas são de dezembro frente a novembro de 2025, com ajuste sazonal.

**Fontes:**
- pmc_202512caderno.pdf — página PDF 17

## D013 — integracao

Relacione a classe CNAE 47.71-7 ao agrupamento de artigos farmacêuticos da PMC.

**Resposta esperada:** A classe corresponde ao comércio varejista de produtos farmacêuticos para uso humano e veterinário; a PMC inclui 4771-7 no agrupamento farmacêutico, médico, ortopédico e de perfumaria.

**Pontos obrigatórios:**
- A classe CNAE 47.71-7 é o comércio varejista de produtos farmacêuticos para uso humano e veterinário.
- A PMC inclui a classe 4771-7 no agrupamento de artigos farmacêuticos, médicos, ortopédicos, de perfumaria e cosméticos.

**Fontes:**
- cnae20.csv — linha 432
- pmc_202512caderno.pdf — página PDF 5

## D014 — integracao

Como a definição de Valor Adicionado ajuda a evitar confundir produção bruta com PIB?

**Resposta esperada:** VA desconta consumo intermediário da produção; PIB acrescenta impostos líquidos de subsídios ao VA, evitando somar novamente insumos.

**Pontos obrigatórios:**
- Valor Adicionado = valor da produção menos consumo intermediário.
- PIB = Valor Adicionado mais impostos líquidos de subsídios.
- Descontar o consumo intermediário evita contar os insumos duas vezes.

**Fontes:**
- pib_mensal_trimestral_metodologia.pdf — página PDF 5
- dicvar_pib_municipal_2002_2020.csv — linha 8

## D015 — sintese

Resuma os instrumentos para reduzir distorções sazonais e alinhar o PIB trimestral às contas anuais.

**Resposta esperada:** X-13 para sazonalidade; benchmarking/Denton para alinhamento anual; objetivos distintos dos dois ajustes.

**Pontos obrigatórios:**
- X-13 para sazonalidade
- benchmarking/Denton para alinhamento anual
- objetivos distintos dos dois ajustes

**Fontes:**
- pib_mensal_trimestral_metodologia.pdf — página PDF 12
- pib_mensal_trimestral_metodologia.pdf — página PDF 13

## D016 — sintese

Que níveis hierárquicos a CNAE 2.0 usa para classificar atividades econômicas e que regionalizações o cadastro territorial associa a cada município paulista?

**Resposta esperada:** CNAE 2.0: seção, divisão, grupo e classe. Cadastro territorial: Região Administrativa, Região Metropolitana, Departamento Regional de Saúde e Região de Saúde, com o município identificado pelo código IBGE de 7 dígitos.

**Pontos obrigatórios:**
- CNAE 2.0: seção, divisão, grupo e classe.
- Cadastro territorial: Região Administrativa, Região Metropolitana, Departamento Regional de Saúde e Região de Saúde.
- O município é identificado pelo código IBGE de 7 dígitos; os códigos CNAE classificam atividades, não territórios.

**Fontes:**
- dicvar_cnae20.csv — linha 2
- dicvar_cnae20.csv — linha 4
- dicvar_cnae20.csv — linha 6
- dicvar_cnae20.csv — linha 8
- dicvar_codigos_municipios_regioes.csv — linha 2
- dicvar_codigos_municipios_regioes.csv — linha 5
- dicvar_codigos_municipios_regioes.csv — linha 7
- dicvar_codigos_municipios_regioes.csv — linha 9
- dicvar_codigos_municipios_regioes.csv — linha 11

## D017 — sintese

Faça uma síntese das restrições ao usar valores nominais e séries encadeadas para acompanhar crescimento.

**Resposta esperada:** nominal inclui preços; volume permite separar mudança de preços; não aditividade dos componentes encadeados.

**Pontos obrigatórios:**
- nominal inclui preços
- volume permite separar mudança de preços
- não aditividade dos componentes encadeados

**Fontes:**
- pib_mensal_trimestral_metodologia.pdf — página PDF 5
- pib_mensal_trimestral_metodologia.pdf — página PDF 6
- pib_mensal_trimestral_metodologia.pdf — página PDF 7

## D018 — limites

Qual foi o PIB de Adamantina em 2028?

**Resposta esperada:** O corpus não fornece PIB municipal de 2028; não extrapolar a base de 2002–2020.

**Pontos obrigatórios:**
- O corpus não fornece o PIB de Adamantina em 2028.
- Não extrapolar a partir da série municipal disponível (até 2020).

**Fontes:**
- pib_municipal_2002_2020.csv — linha 36767

**Limitação de indexação:** A comparação controlada indexa só as primeiras 1.000 linhas de cada tabela. A linha citada no gabarito não recebe embedding; analise esta pergunta separadamente.

## D019 — limites

Qual foi o crescimento dos serviços?

**Resposta esperada:** A pergunta não especifica território, período, indicador nem base de comparação; o corpus tem mais de uma medida de serviços (índices da PMS e valor adicionado de Serviços nas contas trimestrais). A resposta deve apontar essa ambiguidade e, se apresentar um valor, informar território, período e base de comparação, como o crescimento de 2,0% do valor adicionado de Serviços do Brasil no quarto trimestre de 2025 frente ao mesmo período de 2024.

**Pontos obrigatórios:**
- Aponta que a pergunta não especifica território, período, indicador ou base de comparação.
- Todo valor apresentado vem com território, período e base de comparação explícitos.

**Fontes:**
- dic_variaveis_pms.csv — linha 4
- dic_variaveis_pms.csv — linha 5
- pib-vol-val_202504caderno.pdf — página PDF 10

## D020 — limites

O crescimento da indústria do Rio de Janeiro em dezembro de 2025 prova que todas as empresas locais cresceram?

**Resposta esperada:** Não. A indústria do Rio de Janeiro variou 2,3% em dezembro frente a novembro de 2025, com ajuste sazonal, e 10,3% frente a dezembro de 2024, mas o indicador agregado não comprova o comportamento de cada empresa.

**Pontos obrigatórios:**
- Não.
- O indicador agregado não comprova o comportamento de cada empresa.
- Rio de Janeiro: 2,3% em dezembro frente a novembro de 2025, com ajuste sazonal.
- Rio de Janeiro: 10,3% em dezembro de 2025 frente a dezembro de 2024.

**Fontes:**
- pim-pf-regional_202512.pdf — página PDF 15
- pim-pf-br_202512caderno.pdf — página PDF 5
- pim-pf-regional_202512.pdf — página PDF 15
