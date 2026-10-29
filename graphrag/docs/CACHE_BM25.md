# Cache BM25

O cache lexical usa `bm25_nodes.jsonl`, com cabeçalho `schema_version: 1` e registros JSON dos nós textuais, incluindo IDs, metadados e relações, sem embeddings. Arquivos `bm25_nodes.pkl` antigos não são desserializados.

Na próxima sincronização com o corpus disponível, cache ausente, legado ou inválido provoca reconstrução do índice. Em modo somente leitura, gere e instale um novo artefato contendo JSONL antes de iniciar. Não basta renomear o arquivo pickle. A exportação e a instalação de índices exigem o novo nome.

A gravação promove um temporário por substituição atômica. Isso não transforma a promoção da coleção vetorial e a do cache lexical em uma transação conjunta.
