# Como funciona o Graph_Rag

O sistema responde perguntas sobre os boletins SP Economia disponíveis em `data/`. Ele procura trechos relevantes e entrega esse material a um modelo de linguagem para redigir a resposta. Esse processo é chamado RAG: geração apoiada em documentos recuperados.

## 1. Preparar os documentos

O sistema extrai texto, tabelas e imagens dos PDFs e registra arquivo e página de origem. A leitura de imagens depende das opções de OCR/visão e das ferramentas disponíveis; um gráfico pode ser lido incorretamente.

O texto é dividido em trechos menores, chamados chunks. Tabelas pequenas podem ficar inteiras; tabelas maiores podem ser divididas por linha. Cada trecho recebe um identificador determinístico baseado no conteúdo e na ocorrência.

Um modelo local converte os trechos em vetores: listas de números que representam características do texto. O índice Chroma guarda esses vetores; um cache BM25 permite busca por palavras. O manifesto registra configuração e arquivos indexados.

O primeiro boot prepara esse material. Tempo, memória e quantidade de trechos dependem da máquina, do corpus e das opções; não foram medidos nesta versão. Inicializações seguintes podem atualizar apenas fontes alteradas. `RAG_INDEX_READ_ONLY=1` evita sincronizações depois da preparação inicial.

## 2. Entender a pergunta e buscar

O interpretador usa LLM para escolher fontes e reescrever a pergunta. A busca textual combina duas estratégias:

- Busca vetorial: procura trechos semelhantes em significado.
- BM25: procura correspondências de palavras.

A fusão combina as posições dos resultados. Um reranker tenta ordenar os candidatos pela relevância: por padrão, usa um cross-encoder local; pode recorrer a LLM ou scores conforme configuração e disponibilidade. Diversificar documentos é uma preferência, não um limite rígido de três trechos por arquivo.

Tabelas, séries e imagens têm retrievers próprios. Nas tabelas e séries, o modelo propõe apenas um plano JSON com operação e referências às células. Python executa operações permitidas usando Decimal e registra fórmula e operandos. O fluxo não executa Python escrito pelo LLM.

## 3. Ampliar contexto com o grafo

Um grafo é um mapa de entidades ligadas por relações. Há opções distintas:

| Opção | O que faz |
|---|---|
| Estrutura, ativa por padrão | Registra relações entre documentos, páginas e chunks sem extração por LLM |
| Extração LLM, via `--graph` ou `RAG_USE_GRAPH=1` | Propõe relações entre entidades dos textos |
| `RAG_GRAPH_EMBED=1` | Vetoriza também nós do grafo |
| `RAG_ONTOLOGY_DISCOVER=1` | Propõe tipos adicionais durante a inicialização do grafo |

A costura de contexto busca chunks anterior e posterior da mesma página no cache BM25. A engine acrescenta até seis vizinhos sem repetição; não calcula uma cota de 30% nem percorre as arestas persistidas nessa rotina.

Exemplo hipotético: o trecho recuperado contém apenas a continuação de uma frase. Anexar o anterior pode recuperar seu sujeito. Isso pode ajudar, mas não garante uma resposta correta.

A consulta direta ao grafo é outra rotina: usa LLM para expandir termos e recupera caminhos com texto associado. Pode consumir API mesmo num grafo somente estrutural. A aresta `DESCRITA_EM` existe, mas não há uma etapa dedicada que garanta buscar a explicação de cada tabela por ela.

Veja [Grafos](docs/GRAFOS.md) e [Ontologia](docs/ONTOLOGIA.md).

## 4. Redigir a resposta

A engine reúne fontes, elimina repetições e prepara o contexto com arquivo e página. Skills de domínio podem acrescentar instruções: somente o bloco `rag-context` dos arquivos configurados para roteamento entra no prompt.

O modelo redige com esse contexto. O prompt pede citações inline quando solicitadas; a API também devolve fontes e candidatos de evidência separadamente. Contexto vazio gera recusa. Contexto disponível não garante que uma pergunta tenha resposta suficiente nem impede todos os erros do modelo.

O provedor ativo é configurado em `src/llm.py`; não há troca automática para outro provedor após erro de crédito. Embeddings são locais, mas chamadas a um LLM remoto podem enviar trechos dos documentos.

## 5. Conferir números e evidências

Cada ocorrência numérica é comparada a trechos locais, considerando indicador, período, região e unidade. Encontrar o mesmo número isolado não basta. A verificação é uma heurística e pode exigir revisão de uma resposta correta ou deixar de reconhecer contexto distribuído.

`claim_evidence` registra fontes candidatas por afirmação. `calculations` preserva a conta e os valores usados: correção aritmética não confirma que o modelo escolheu as células certas. `usage` registra tokens disponíveis; custo ausente é `null`, não zero.

A aplicação limita consultas simultâneas, fila, chamadas LLM e rerank por processo. Sobrecarga pode retornar 503; trabalho já iniciado numa thread pode continuar após timeout HTTP.

## Estado atual

As alterações foram feitas sem executar testes, avaliações ou o servidor. O roteiro de comparação entre busca híbrida, estrutural e grafo LLM está preparado, mas depende de gabaritos revisados e execução futura. Exemplos didáticos não são resultados medidos.

Veja [README](README.md), [Detalhes técnicos](docs/PYTHON.md) e [Confiabilidade](docs/CONFIABILIDADE.md).
