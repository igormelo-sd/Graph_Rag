# RAG simples, sem grafos

Organização do código e execução de todas as suítes: [guia de manutenção](../docs/REFATORACAO.md).

Fluxo tradicional: **documentos → trechos → embeddings locais → busca exata por
similaridade de cosseno → resposta com fontes**. O índice é um arquivo JSON,
adequado a bases pequenas. A recuperação não usa grafo ou extração de entidades.

Os modelos, parâmetros e prompt de resposta são compartilhados com a outra
versão por `../comparacao`. As chamadas LLM usam a mesma factory do GraphRAG.
Padrões: `gpt-4o-mini`, `BAAI/bge-m3`, trechos de 1.024 caracteres, sobreposição
de 200, top-k 5 e temperatura zero.

## Comparação experimental

Para comparar com GraphRAG, siga [o roteiro comum](../comparacao/README.md).
Ele prepara o corpus uma única vez e usa os mesmos trechos e vetores, evitando
diferenças de extração de PDF e tabelas. Na raiz `Graph_Rag`:

```powershell
.\.venv\Scripts\python.exe comparacao/run.py preparar
.\.venv\Scripts\python.exe rag_simples/rag.py comparar "Sua pergunta"
```

Use o mesmo ambiente com as dependências de `graphrag/requirements.txt` e
credenciais em `comparacao/.env`. Altere modelos em `comparacao/config.json`.

## Uso simples independente do experimento

Para trabalhar somente com PDF de texto selecionável, TXT e Markdown em UTF-8:

```powershell
cd rag_simples
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env

# Corpus comum por padrão; pode indicar outra pasta.
.\.venv\Scripts\python.exe rag.py indexar
.\.venv\Scripts\python.exe rag.py indexar --documentos documentos
.\.venv\Scripts\python.exe rag.py perguntar "Quando acontecem as oficinas?"
.\.venv\Scripts\python.exe rag.py perguntar "Quando acontecem as oficinas?" --somente-busca
```

Preencha a chave do provedor no `.env`. Nesse uso, variáveis locais podem
substituir os padrões comuns. Ao alterar o corpus, o modelo de embeddings ou o
processamento, execute `indexar` novamente. Índices antigos com embeddings da
API são rejeitados e precisam ser reconstruídos. A busca e os embeddings são
locais; a geração usa o provedor configurado.

O fluxo simples acima não faz a extração especializada de tabelas usada pelo
preparo experimental. Não há OCR, reranking, busca híbrida ou memória de conversa.
O modelo recebe as fontes e deve citar `[1]`, `[2]` etc.; não existe validação
automática da correção das citações. Contexto insuficiente deve ser declarado.

## Testes sem chamadas reais

```powershell
python -m unittest discover -s tests -v
```

Os testes simulam embeddings e respostas; não avaliam qualidade semântica.
