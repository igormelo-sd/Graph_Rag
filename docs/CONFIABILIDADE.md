# Precisão, evidências e operação

Estas alterações foram implementadas sem executar testes, avaliações ou o servidor.
A resolução de dependências consultou metadados do PyPI; não instalou o aplicativo.

## Validação contextual

Cada ocorrência de número recebe uma verificação própria. A mesma taxa pode estar
correta em uma afirmação e incorreta em outra. A correspondência exige indicador,
período, região e unidade explícitos e compatíveis no trecho local. Valores repetidos
ou múltiplas observações ambíguas permanecem para revisão. Inteiros de um dígito
também são examinados; números inteiros com separador de milhar são normalizados.

`validation.method=contextual_heuristic` identifica uma heurística conservadora,
não uma prova semântica. O vocabulário compartilhado fica em `src/domain_ontology.py`. Escala, setor, fonte, natureza, base e cobertura também são conferidos quando reconhecidos; São Paulo sem qualificação mantém ambiguidade.
Dimensões não reconhecidas, afirmações qualitativas e contexto distribuído entre
várias linhas podem gerar revisão mesmo quando a resposta está correta.
`validation.requires_review` sinaliza essas situações; o texto não é apagado.
`verified` agora conta correspondências contextuais, não simples presenças de valores.

## Evidência por afirmação

`claim_evidence` contém o texto, posições na resposta, fontes candidatas, arquivo,
página, ID do trecho e ocorrências numéricas com os motivos de revisão.
Afirmações sem números recebem candidatos por similaridade lexical, nunca
confirmação automática. Os índices `source_index` referem-se a `sources` da mesma
resposta. `calculation_candidates` aponta cálculos cujo resultado textual aparece
na afirmação; é uma associação candidata, não uma verificação de causalidade.

## Cálculos

Os retrievers pedem ao modelo apenas um plano JSON com operação e referências
a células extraídas. Python calcula com `Decimal`: diferença, variação percentual,
pontos percentuais, soma e média. A variação usa `(final - base) / base * 100`;
base não positiva, unidades incompatíveis, células repetidas ou operandos ausentes
das fontes impedem a operação. Há limites de tamanho e magnitude; nenhum Python
gerado pelo modelo é executado.

`calculations` preserva operação, fórmula, operandos e trechos onde os valores
aparecem. `arithmetic_verified=true` confirma apenas a conta; a escolha dos
operandos pelo modelo continua com `semantic_status=requires_review`. Valores
extraídos não se tornam corretos apenas por participarem de uma conta correta.
O prompt final exige reutilizar cálculos existentes e não criar operações novas.
Resultados derivados sem correspondência documental permanecem para revisão
na validação numérica; consulte a trilha de cálculo separadamente.

## Controle de carga

O contrato ontológico acrescenta verificações de natureza da medida, escala, setor, fonte, base e cobertura. Operandos precisam de indicador, território, unidade e natureza únicos; períodos comparados devem ser distintos, de mesma granularidade e estar em ordem base/final. Soma de taxas, estoques e variações exige revisão. Apoio contextual na fonte continua obrigatório. Esses critérios conservadores podem recusar contas legítimas quando os documentos omitem dimensões.

O campo `ontology` expõe dimensões da pergunta, observações candidatas com proveniência e auditorias de extração disponíveis nos nós recuperados. Não é certificado de verdade documental. O hash do modelo invalida índices antigos; esta atualização não executou sua reconstrução. Os casos em `evaluation/ontology_cases.example.jsonl` ainda exigem gabarito documental e revisão.

Observações por célula preservam cabeçalhos, linhas e notas; associação geométrica de contexto requer revisão. Relações positivas negadas são rejeitadas por padrões, e associação não é prova causal. `ontology.comparisons` descreve os cálculos sem gravá-los como fatos; `ontology.retrieval_paths` expõe caminhos documentais. Divergências entre fontes ficam para revisão, sem prioridade automática de narrativa sobre tabela. `clarification` solicita o recorte de São Paulo quando ambíguo; `knowledge` e `GET /knowledge` descrevem candidatos disponíveis e lacunas solicitadas. O cadastro territorial/setorial é limitado, e ausência no índice não comprova ausência nos documentos. Veja [ESTATISTICAS_GRAFO.md](ESTATISTICAS_GRAFO.md).

| Configuração | Padrão | Função |
|---|---:|---|
| `RAG_QUERY_CONCURRENCY` | 2 | Consultas ativas por processo |
| `RAG_QUERY_QUEUE` | 4 | Consultas aguardando vaga |
| `RAG_QUEUE_WAIT` | 5 | Espera máxima na fila, em segundos |
| `RAG_LLM_CONCURRENCY` | 4; Ollama: 1 | Chamadas simultâneas ao modelo |
| `RAG_RERANK_CONCURRENCY` | 1 | Rerankings simultâneos |
| `RAG_RESOURCE_WAIT` | 10 | Espera por vaga de modelo/reranker, em segundos |

Fila cheia ou espera excedida retorna HTTP 503 com `Retry-After` quando a falha
chega à API. Retrievers mantêm seus fallbacks para falhas parciais. Os limites são
por processo: múltiplos workers multiplicam a capacidade. Chamadas síncronas já
iniciadas podem continuar após timeout HTTP, mantendo sua vaga de recurso até
terminar. Configure antes de iniciar o processo. O timeout da consulta começa
depois da admissão; a espera da fila tem seu próprio limite.

## Uso e custo

`usage` agrega chamadas de interpretação, retrieval, extração, cálculo, síntese e
popups instrumentadas pela factory. Tokens são reportados pelo provedor quando
disponíveis. `token_usage_complete=false` indica que há chamadas sem contagem.
`cost_usd=null` significa custo indisponível, não custo zero. Para estimá-lo com
tarifas médias explícitas, configure `RAG_INPUT_COST_PER_MILLION_USD` e
`RAG_OUTPUT_COST_PER_MILLION_USD`. Modelos com preços diferentes exigem tarifas
médias apropriadas; o campo `cost_method` identifica essa aproximação.

## Comparação entre modos — execução futura

`scripts/evaluate_retrieval.py` prepara a comparação híbrido, estrutural e grafo
extraído por LLM em processos separados. Mantém as mesmas perguntas e fontes
base; desativa HyDE/deep search e não usa reescrita variável. O modo estrutural
expande vizinhos e consulta observações locais; o modo LLM também consulta relações por sinônimos. Cada modo tem uma variante `_no_ontology`, totalizando seis condições. Essa desativação é parcial: contratos de extração e evidência permanecem. `competency_match` mede reconhecimento de dimensões da pergunta, sem avaliar correção da resposta. O índice fica somente
leitura e os caches de grafo ficam no diretório de saída.

1. Reconstrua o índice com o pipeline atual antes da avaliação, quando autorizado.
2. Copie `evaluation/cases.example.jsonl` e preencha um gabarito conferido nos PDFs:
   `expected_sources`, `expected_answer_contains` e `gold_reviewed=true`.
3. Só após autorização para executar e consumir LLM, rode:

```powershell
python scripts/evaluate_retrieval.py evaluation/cases.jsonl --output evaluation/runs/primeira --repeats 3
```

Os exemplos são rascunhos, não gabaritos. Sem revisão, o script recusa pontuar;
`--allow-unscored` permite futuramente coletar respostas sem nota. O relatório
guarda respostas completas, erros, latência, recall documental e correspondência
de fragmentos do gabarito. Essa última métrica é uma aproximação textual, não
acurácia semântica. A avaliação humana das afirmações continua necessária.
O custo das consultas não inclui construir o grafo; tempo e uso de LLM da
inicialização são registrados separadamente em `startup_seconds` e `startup_usage`.
Caches aquecidos e frios não devem ser comparados como
se fossem equivalentes. Nenhuma avaliação foi executada nesta implementação.

## Dependências reproduzíveis

`requirements.in` e `requirements-dev.in` são as entradas editáveis.
`requirements.txt` e `requirements-dev.txt` fixam dependências diretas e transitivas
com hashes, resolvidas para **Windows x64 e Python 3.11**, usando uv 0.12.22.
`.python-version` registra o alvo. A compatibilidade do código ainda não foi testada.

```powershell
pip install --require-hashes -r requirements.txt
```

Para atualizar deliberadamente o conjunto, instale `uv==0.12.22` e execute
`scripts/lock_dependencies.ps1`. Para outro sistema/Python, gere locks específicos
com os parâmetros do script; não presuma que o lock Windows cobre Linux.
As bibliotecas foram resolvidas, mas não instaladas no ambiente do aplicativo.
Os arquivos de pesos dos modelos e ferramentas externas de OCR não são cobertos
pelo lock Python.

## Cobertura e orçamento documental

O diagnóstico em knowledge.retrieval_coverage é uma checagem conservadora sobre candidatos recuperados, sem garantia semântica. O orçamento omite blocos inteiros que não cabem, podendo deixar lacunas; não prova ausência no corpus. Fontes, cálculos e gráficos retornados são limitados às evidências incluídas. Veja [Melhorias do RAG](MELHORIAS_RAG.md). Verificação em execução permanece pendente.

