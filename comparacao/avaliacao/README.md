# Banco de perguntas para RAG simples × GraphRAG

O banco foi elaborado a partir dos 20 arquivos de `graphrag/data`, o corpus
definido em `comparacao/config.json`. Os arquivos correspondentes em `data` da
raiz são idênticos. O PDF adicional `data/pib_municipal_ed2019.pdf` foi inspecionado
no filtro, mas não foi usado nos gabaritos por estar fora do corpus configurado.

Leia primeiro [o filtro dos PDFs](filtro_pdfs.md).

| Categoria | Desenvolvimento | Teste |
|---|---:|---:|
| Factual e conceitos documentados | 5 | 25 |
| Numérica e leitura de tabelas | 5 | 25 |
| Integração de fontes, recortes ou cálculos | 4 | 20 |
| Síntese | 3 | 15 |
| Ausência de informação, ambiguidade ou premissa incorreta | 3 | 15 |
| **Total** | **20** | **100** |

## Arquivos

- `desenvolvimento.jsonl`: perguntas para ajustar o sistema.
- `teste.jsonl`: perguntas reservadas à avaliação final.
- `desenvolvimento.md` e `teste.md`: versões legíveis com gabaritos e referências.
- `rubrica.md`: critérios para avaliar as respostas.
- `manifesto_corpus.json`: hashes, tamanhos e distribuição das perguntas.
- `validar.py`: checagem local de integridade, fontes e separação das perguntas.

Cada linha JSON é uma pergunta com ID, categoria, resposta candidata, pontos
obrigatórios, comportamento esperado e referências. Nas referências:

- PDF: `pagina_pdf` é a página física a partir de 1, não a página impressa.
- CSV: `linha` é o registro lógico a partir de 1, incluindo o cabeçalho; códigos
  e valores literais permanecem como texto.
- XLSX: `aba` e `celula` localizam o valor; os cabeçalhos estão preservados para
  distinguir anos, territórios, agregados e unidades. São valores salvos no arquivo,
  sem recalcular fórmulas.
- `calculo_esperado` identifica resultados calculados ou arredondados, com unidade
  e tolerância; eles não são novos fatos do corpus.

## Revisão antes do experimento final

Todas as perguntas têm `revisao_humana.status = "pendente"`. Verifique a pergunta,
o gabarito, as fontes e as interpretações necessárias. Corrija divergências e
registre revisor, data e observações; use `aprovada` somente após essa revisão.
Os exemplos de insuficiência de informação dizem respeito ao corpus congelado,
não a todas as fontes públicas existentes.

A divisão é por pergunta, com cobertura de um corpus comum. Perguntas de
desenvolvimento e teste não são idênticas, mas podem compartilhar documentos e
conceitos. Não trate esse desenho como generalização para documentos inéditos.
As proporções foram escolhidas para cobrir dificuldades do projeto; não foram
estimadas a partir de uma amostra de consultas reais de usuários.

## Uso

1. Revise as 20 perguntas de desenvolvimento e use-as para os ajustes.
2. Revise e congele o conjunto final. Se a banca exigir teste cego, atribua sua
   revisão final a uma pessoa que não participe do ajuste dos sistemas.
3. Congele corpus, perfil, versões dos modelos e código. O manifesto permite
   detectar alterações nos arquivos.
4. Envie ao sistema somente `pergunta`. Não envie gabaritos, pontos obrigatórios,
   fontes de referência ou categoria no prompt. Não indexe esta pasta.
5. Use a mesma pergunta e perfil nas duas implementações. Registre respostas,
   fontes recuperadas, duração, chamadas e uso de tokens em
   `comparacao/artefatos/resultados/`.
6. Avalie com a rubrica, alternando a ordem dos sistemas e ocultando seus nomes
   dos avaliadores. Compare resultados gerais e por categoria.

O executor atual recebe uma pergunta por chamada; o banco não dispara uma
avaliação nem chamadas de modelos automaticamente. Exemplo:

```powershell
.\.venv\Scripts\python.exe comparacao/run.py perguntar "Sua pergunta" --versao rag_simples
.\.venv\Scripts\python.exe comparacao/run.py perguntar "Sua pergunta" --versao graphrag
.\.venv\Scripts\python.exe comparacao/avaliacao/validar.py
```

Os gabaritos citam todas as evidências necessárias, mas não impõem igualdade
literal de texto. Respostas corretas com redação diferente devem ser aceitas.
