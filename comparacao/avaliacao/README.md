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

## Limitação de indexação das tabelas

Na comparação controlada, só as primeiras 1.000 linhas de cada tabela recebem
embedding. As perguntas D011, D018, T046–T055, T065, T082, T087, T088, T094 e
T095 citam linhas fora desse teto. Veja [a limitação no README da comparação](../README.md#limitação-tabelas-com-mais-de-1000-linhas)
e reporte esse grupo separadamente.

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

## Coleta reproduzível da aplicação GraphRAG

`experimento.py` executa as perguntas de desenvolvimento no aplicativo completo.
Use `--versao principal` para o RAG principal ou `--versao graphrag` (padrão)
para a variante GraphRAG. Cada opção carrega sua própria engine, `.env`, corpus
resolvido e configuração de índice, em processos separados. O manifesto registra
essa escolha; a coleta não transforma os motores em uma mesma implementação.
Esse fluxo tem busca tabular adicional e **não substitui** a comparação controlada
entre implementações em `comparacao/run.py`. Exemplo com modelo local instalado:

```powershell
.\.venv\Scripts\python.exe comparacao/avaliacao/experimento.py coletar --provider ollama --model qwen3:4b-instruct --ids D004,D005,D011 --allow-unreviewed --output comparacao/artefatos/resultados/minha_rodada
.\.venv\Scripts\python.exe comparacao/avaliacao/validar.py --split desenvolvimento
.\.venv\Scripts\python.exe comparacao/avaliacao/experimento.py coletar --versao principal --provider ollama --model qwen3:4b-instruct --context-tokens 1000 --ids D004,D005,D011 --allow-unreviewed --output comparacao/artefatos/resultados/minha_rodada_principal
```

O modelo é obrigatório e é usado na interpretação, síntese e explicações, com
temperatura zero. Roteadores `openrouter/free`, `openrouter/auto`, curingas e
`latest` são recusados. A configuração vale somente para o processo. O manifesto
registra hashes do corpus, código e perguntas, versões das bibliotecas,
configurações selecionadas e digest do modelo Ollama. IDs retornados pelo
provedor ficam nas respostas; identidade ausente permanece não verificada e
identidade divergente encerra a rodada. O executor encerra também em erro técnico,
sem mudar modelo ou provedor. Serviços remotos podem atualizar pesos mesmo sob
um ID estável; esse limite deve constar do relato experimental. Dependências de
pesos e índice devem permanecer congeladas separadamente. `--context-tokens 1000`
reduz o orçamento de evidências para testar um servidor com janela curta; registre
esse ajuste e use o mesmo orçamento em comparações. Ele não altera a janela
configurada no servidor do modelo.

O diretório de saída deve ser novo para evitar sobrescrever resultados. Há uma
resposta por arquivo e uma ficha `revisao.json`. O aplicativo recebe somente a
pergunta, sem o gabarito. `--allow-unreviewed` permite coletar respostas com
gabaritos pendentes, mas não as pontua automaticamente.

Uma pessoa deve revisar o gabarito e preencher cada ponto obrigatório como
atendido ou omitido, com evidência/justificativa, além das quatro notas 0–2 da
rubrica: correção, apoio documental, completude e qualificação. Depois:

```powershell
.\.venv\Scripts\python.exe comparacao/avaliacao/experimento.py pontuar comparacao/artefatos/resultados/minha_rodada/revisao.json
```

O resumo mantém as médias separadas e conta pontos omitidos. Rejeita notas sem
justificativa, pontos não revisados, avaliador ausente e gabaritos não aprovados.
Assim, uma resposta pode estar correta no que afirma e receber uma nota baixa de
completude por omitir, por exemplo, a não aditividade das séries encadeadas.

Na curadoria assistida de 22/10/2026, D012 passou a explicitar a comparação mensal
com ajuste sazonal; D009 recebeu ajuste de espaço no trecho extraído do PDF.
Os resultados históricos devem ser identificados pelo hash antigo das perguntas.
O conjunto reservado de teste não foi alterado e a revisão humana continua
pendente. A integridade documental normaliza somente espaços antes de pontuação
na extração dos PDFs; não elimina diferenças de conteúdo, sinais ou valores.
