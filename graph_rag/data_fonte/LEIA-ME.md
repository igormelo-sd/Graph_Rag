# Seleção do corpus

Os dois PDFs locais foram movidos de Guardar para esta pasta. Os 14 arquivos de apoio foram copiados, preservando os originais em Guardar.

## Documentos
- Cinco PDFs do IBGE e 16 arquivos do Seade: URLs registradas em fontes.json. As referências do Seade incluem a página do conjunto e do recurso, além do link de download. A correspondência foi feita pelo catálogo oficial, sem comparação byte a byte dos arquivos remotos.
- pib_mensal_trimestral_metodologia.pdf: metodologia para acompanhar as séries de PIB.
- pib_municipal_ed2019.pdf: publicação de PIB municipal; conferir período e metodologia antes de comparar com séries recentes.

## Dados de apoio
- Três planilhas de PIB: regional, anual de 2023 e relatório do segundo trimestre de 2026.
- Indústria: base-pim_spbrasil (1).csv, versão previamente identificada como mais atual entre as duas disponíveis. Não foi encontrado dicionário específico de PIM em Guardar.
- Comércio e serviços: bases PMC e PMS acompanhadas dos seus dicionários.
- CNAE e códigos municipais/regionais: classificações e respectivos dicionários para identificação de atividades e territórios.
- PIB municipal 2002–2020 e respectivo dicionário: série histórica complementar.

## Preparação pendente
Esta é uma seleção de arquivos, ainda sem ingestão ou testes no projeto. Os CSVs exigem atenção à codificação e ao separador; as planilhas têm cabeçalhos que precisam ser tratados. Os documentos possuem períodos e abrangências diferentes: não presumir comparabilidade automática. As bases maiores de exportações, empresas e população permanecem em Guardar para seleção posterior.

## Substituição por fechamento anual — 07/10/2026

Os boletins de indústria e comércio de meses isolados de 2026 foram substituídos pelas edições de dezembro de 2025, que incluem comentários e resultados acumulados de janeiro a dezembro. O boletim de PIB do segundo trimestre de 2026 foi substituído pelo quarto trimestre de 2025, com seção de resultados do ano completo.

- pim-pf-br_202512caderno.pdf: indústria brasileira, fechamento de 2025.
- pim-pf-regional_202512.pdf: indústria regional, fechamento de 2025.
- pmc_202512caderno.pdf: comércio, fechamento de 2025.
- pib-vol-val_202504caderno.pdf: PIB nacional, quarto trimestre e ano de 2025.

São publicações mensais/trimestrais com balanço anual, não anuários nem séries históricas integrais. Para análises de vários anos, usar os CSVs e as planilhas presentes nesta pasta. Os quatro PDFs anteriores foram movidos para Guardar; suas fontes estão em Guardar/fontes_boletins_2026.json. As fontes da seleção atual estão em fontes.json.

