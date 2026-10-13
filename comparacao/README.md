# Comparação entre RAG simples e GraphRAG

Organização do código e execução de todas as suítes: [guia de manutenção](../docs/REFATORACAO.md).

O perfil comum está em [config.json](config.json). Ele é aplicado como padrão nos
dois aplicativos e imposto nos comandos de comparação: variáveis locais de modelo,
recuperação ou endpoint não podem substituir o perfil nessa execução.

| Parâmetro | Valor comum |
|---|---|
| Provedor / modelo de resposta | OpenAI / `gpt-4o-mini` |
| Embeddings | `BAAI/bge-m3`, locais, CPU, normalizados |
| Lote / comprimento máximo do embedding | 16 / 8.192 tokens do modelo |
| Trechos / sobreposição | 1.024 / 200 caracteres, SentenceSplitter |
| Busca inicial | Similaridade de cosseno exata, 5 trechos |
| Contexto de evidências | Até 12.000 tokens estimados por caracteres / 4 |
| Resposta máxima / temperatura | 1.200 tokens / 0 |
| Corpus | `../graphrag/data` |

Também são iguais o prompt final, a numeração de fontes e a política de incluir
trechos inteiros que caibam no orçamento. O limite de contexto é uma estimativa;
não corresponde a uma contagem exata do tokenizer do modelo.

## Preparação e execução

Use **o mesmo ambiente Python** para as duas versões. Na raiz `Graph_Rag`, com
Python 3.11 / Windows x64 para as dependências fixadas:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r graphrag/requirements.txt
Copy-Item comparacao/.env.example comparacao/.env
```

Preencha `OPENAI_API_KEY` em `comparacao/.env`. Os comandos controlados usam esse
arquivo comum. Modelos de embeddings ausentes são baixados no primeiro uso.
Para trocar de provedor ou modelo, altere `config.json` e configure a chave
correspondente. Evite roteadores que escolham modelos diferentes a cada chamada.

```powershell
# Extrai e divide o corpus uma única vez e grava os mesmos vetores para ambos.
.\.venv\Scripts\python.exe comparacao/run.py preparar

.\.venv\Scripts\python.exe comparacao/run.py perguntar "Sua pergunta" --versao rag_simples
.\.venv\Scripts\python.exe comparacao/run.py perguntar "Sua pergunta" --versao graphrag

# Perguntas globais usam comunidades automaticamente no GraphRAG.
.\.venv\Scripts\python.exe comparacao/run.py perguntar "Quais os temas dos documentos?" --versao graphrag
```

Os mesmos comandos têm entradas nos aplicativos:

```powershell
.\.venv\Scripts\python.exe rag_simples/rag.py comparar "Sua pergunta"
.\.venv\Scripts\python.exe graphrag/main.py --comparar "Sua pergunta"
```

O índice comum fica em `comparacao/artefatos/index.json`. O preparo usa a ingestão
e o processamento do GraphRAG para ambos, incluindo tabelas. O comando verifica
hashes dos arquivos e do perfil antes de consultar; mudanças exigem novo preparo.
Ele não substitui os índices Chroma usados pelo aplicativo completo.

## Duas implementações

| Versão | Recuperação e contexto |
|---|---|
| `rag_simples` | Trechos iniciais por similaridade, sem grafo |
| `graphrag` | Expansão por entidades e estrutura, contexto dos documentos; perguntas globais usam resumos de comunidades |

Existe uma única opção GraphRAG na comparação. Não há seleção de uma versão
reduzida ou uma opção adicional para ativar os recursos completos. Os antigos
nomes `simples`, `grafo` e `grafo_completo` foram removidos: use os nomes das pastas.
O antigo argumento `--comparacao-completa` também foi removido.

O grafo controlado usa regras e entidades cadastradas, sem extração de relações
por LLM. A extração LLM do aplicativo permanece disponível fora desse fluxo.
“GraphRAG” identifica aqui a estratégia do experimento; não significa que todas
as opções da API de produção participem do experimento.

Nos comandos controlados, não participam BM25, reranking, reescrita da pergunta,
skills, calculadoras, HyDE ou enriquecimento LLM da ingestão. Os chats e a API
normais conservam sua arquitetura e permitem configurações locais; **use os
comandos acima para a comparação experimental**, pois alinhar modelos sozinho
não torna esses fluxos equivalentes.

O resultado JSON registra parâmetros, hashes do corpus/perfil, IDs iniciais,
fontes usadas, orçamento estimado e tempos. O tempo de recuperação inclui a
transformação do contexto; no modo global, inclui chamadas para resumos quando
o cache estiver vazio e a consolidação para a pergunta. A preparação do grafo
e o carregamento dos modelos ficam fora desse tempo. A geração mede a síntese
final. Esses tempos não representam o custo total de cada arquitetura.

Registre separadamente execuções com cache frio e quente. Use o mesmo conjunto
de perguntas e gabaritos revisados, repetições e ordem alternada. Temperatura
zero reduz variação, mas não garante respostas idênticas. Para o experimento
final, prefira um identificador de versão fixa do modelo e registre a data.
Resumos são derivados e suas fontes candidatas não comprovam correção das citações.

## Validação local

```powershell
.\.venv\Scripts\python.exe -m pytest comparacao/tests rag_simples/tests -q --capture=sys
```

Os testes simulam os modelos e verificam equivalência da busca inicial, prompt,
orçamento, expansão, processamento global e rejeição de corpus/perfil alterado.
Eles não medem qualidade de respostas reais. Índices antigos do RAG simples,
com embeddings da API, exigem reconstrução para o novo formato local.
