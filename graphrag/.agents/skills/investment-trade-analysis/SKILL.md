---
name: investment-trade-analysis
description: >
  Estruturar e revisar análises de investimentos anunciados e comércio exterior
  paulista. Usar em perguntas sobre projetos de investimento, setores e regiões
  receptoras, exportações, importações, saldo comercial, parceiros, produtos,
  participação, valor, volume, preços e variação cambial.
---

# Análise de Investimentos e Comércio Exterior

## Objetivo

Evitar comparações indevidas entre anúncios e execução, ou entre valor comercial,
volume físico e preço. Preservar período, moeda, cobertura e status do dado.

## Fluxo

1. Identificar natureza do investimento: anunciado, previsto, contratado,
   iniciado ou realizado.
2. Confirmar janela temporal, moeda, preços correntes ou constantes e território.
3. Detectar projetos repetidos ou atualizados antes de agregar anúncios.
4. Separar investimento produtivo, infraestrutura e operações financeiras.
5. No comércio exterior, separar exportação, importação e saldo.
6. Distinguir valor, quantidade e valor unitário.
7. Comparar produtos e parceiros usando denominador explícito.
8. Citar fonte e página para cada valor, período e classificação.

## Referências

- Consultar [conceitos.md](references/conceitos.md) para métricas de investimento,
  comércio exterior e controles de comparabilidade.

<!-- rag-context:start -->
## Contexto para síntese RAG

- Classificar investimento como anunciado, previsto, contratado, iniciado ou
  realizado. Não apresentar anúncio como desembolso executado.
- Confirmar período, moeda, preços correntes ou constantes, território e setor
  antes de agregar ou comparar valores.
- Evitar dupla contagem de projetos republicados, ampliados ou distribuídos por
  mais de um município, salvo quando a fonte fornecer parcelas não sobrepostas.
- Em comércio exterior, calcular saldo como exportações menos importações.
  Distinguir superávit de aumento das exportações e déficit de queda do saldo.
- Separar valor comercial, volume físico e valor unitário. Mudança no valor não
  prova mudança equivalente na quantidade.
- Informar denominador de participações por produto, setor, parceiro ou região.
- Não atribuir variações a câmbio, preços internacionais ou demanda sem suporte
  explícito nos documentos.
- Não introduzir fatos externos. Usar este contexto apenas como regra de
  interpretação dos documentos recuperados.
<!-- rag-context:end -->
