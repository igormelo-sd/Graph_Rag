# Ontologia — vocabulário orientador do grafo

A ontologia fornece categorias sugeridas ao extrator de relações. Funciona como a legenda de um mapa, mas não constitui uma garantia formal de que toda entidade será classificada corretamente. Código: `src/graph_ontology.py` e `src/graph_indexing.py`; veja [Grafos](GRAFOS.md).

## Tipos fixos

| Tipo | Uso pretendido |
|---|---|
| `Indicador` | PIB, taxas e medidas |
| `Setor` | Ramos de atividade |
| `Região` | Recortes geográficos |
| `Período` | Datas e intervalos |
| `FonteDados` | Instituições e bases estatísticas |
| `Tabela` | Tabelas documentais |
| `Grafico` | Gráficos documentais |
| `Pagina` | Página de origem |
| `Documento` | Arquivo de origem |

A lista alimenta `allowed_entity_types` do `DynamicLLMPathExtractor`. Ela orienta a extração; ausência de `Municipio` não torna municípios necessariamente invisíveis: o modelo pode representá-los como `Região`. A proveniência documental deve ser conferida nos nós recuperados, sem presumir que qualquer tripla prove um fato.

## Descoberta opcional

`RAG_ONTOLOGY_DISCOVER=1` habilita a descoberta durante a inicialização do grafo. O sistema amostra até seis trechos, priorizando texto narrativo, e pede ao LLM até quatro categorias adicionais em JSON. Essa amostra não garante representar todo o corpus.

O prompt solicita PascalCase sem acentos. A implementação mantém caracteres alfanuméricos, coloca a primeira letra em maiúscula, elimina nomes repetidos e restringe o tamanho a 3–20 caracteres. Ela não remove acentos nem converte todas as palavras para PascalCase.

O cache fica em `<raiz>/graph_store/ontology.json`, inclusive quando outro diretório é configurado para o grafo por `RAG_GRAPH_DIR`. Com cache válido, não há nova chamada; sem cache ou com reconstrução forçada, há uma tentativa de descoberta. JSON inválido ou falha do LLM costuma resultar em lista vazia cacheada; falhas ao gravar o cache ainda podem propagar.

## Limites e revisão

Categorias novas podem introduzir ruído ou sobreposição. Compare extração com e sem descoberta e audite os resultados antes de atribuir ganho à ontologia. Ela não ranqueia fontes nem garante correção semântica das relações.

`ontology.json` é gerado: inspecione-o, mas ajuste prompt/configuração e regenere pelo fluxo de indexação em vez de editar o cache manualmente. Quando todas as opções de grafo estão desligadas, a descoberta isolada não o inicializa.

A descoberta e sua contribuição experimental ainda não foram executadas nesta atualização. Veja [CONFIABILIDADE.md](CONFIABILIDADE.md).
