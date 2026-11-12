# Recuperação e montagem de evidências

Implementação de 6 de outubro de 2026. Não executada nem avaliada nesta etapa.

## Fluxo

1. As alternativas da busca híbrida passam por `preserve_query`. No modo deep search a expansão interna é desativada para evitar multiplicação de consultas.
2. Os candidatos de texto, tabelas, séries, imagens e grafo entram em uma fusão RRF global. O reranker configurado refina até 80 candidatos; os demais permanecem disponíveis para cobertura. Falhas preservam RRF e são registradas.
3. A seleção reserva candidatos para indicador, território, período e setor solicitados antes de priorizar variedade documental. Conteúdo exatamente repetido na mesma fonte/página é deduplicado; parágrafos integralmente contidos em trechos anteriores com mesmos qualificadores também podem ser omitidos. Versões e outras fontes permanecem. Não há deduplicação aproximada nem remoção de sobreposição parcial, para evitar remover ressalvas.
4. A cobertura é verificada por observações com recortes associados. Uma lacuna permite uma única busca textual complementar, com limite de 30 segundos. Essa busca não repete extração ou cálculo tabular.
5. O contexto recebe blocos completos: texto com origem, células com títulos/notas literais ou resultados estruturados com todas as suas fontes. Blocos que não cabem são omitidos integralmente. Até dois vizinhos narrativos por semente podem acompanhar os seis primeiros candidatos, na mesma página/seção, independentemente do grafo.
6. A síntese recebe uma sinalização de cobertura parcial. A resposta expõe apenas fontes presentes no contexto; cálculos exigem também fórmula presente, e gráficos exigem que suas fontes estejam incluídas.

`knowledge.retrieval_coverage` informa `missing`, `status` e `semantic_verified: false`. A cobertura candidata não prova suficiência semântica, compatibilidade metodológica nem ausência da informação no corpus. A ontologia desativada ou não reconhecendo um recorte limita esta checagem.

## Tabelas e séries

Quando todos os nós selecionados têm `table_structure` compatível, os valores e cabeçalhos literais são reutilizados sem extração pelo LLM. O seletor de operações continua usando planos JSON e a aritmética continua em Decimal. Não se trata de cálculo inteiramente sem LLM. Estruturas ausentes/incompatíveis mantêm o caminho anterior; uma estrutura literal sem formato temporal válido retorna evidências brutas em vez de reescrever os valores.

## Configuração e limites

- `RAG_FINAL_TOP_N`: candidatos para montagem do contexto, padrão 30, intervalo 5–80. Fontes adicionais de blocos estruturados/vizinhos não estão incluídas nesse número.
- `RAG_MAX_CONTEXT_TOKENS`: orçamento estimado por caracteres, preservado. Não é contagem exata do tokenizer nem orçamento total do prompt.
- `RAG_QUERY_FUSION_QUERIES`: máximo de consultas internas; no modo aprofundado usa 1.
- `RAG_HYDE`: mantém ativação opcional, com instrução explícita para não inventar valores, tendências ou causas. A proteção de reescrita não constitui garantia sobre toda saída gerada.

O splitter agora prioriza títulos Markdown, parágrafos, linhas e frases antes de espaços/caracteres. O fingerprint do pipeline foi alterado: a reconstrução do índice é necessária na próxima execução autorizada. Nenhum índice foi reconstruído nesta etapa. A expansão narrativa usa metadados existentes de página, seção e posição; não cria uma árvore completa de seções e não atravessa páginas.

## Verificação pendente

Há casos de regressão preparados em `tests/test_rag_selection.py`, sem execução. Importação, compatibilidade com dependências, latência, recuperação, cobertura e qualidade das respostas ainda precisam ser avaliadas com gabaritos revisados. Não há resultados experimentais atribuídos a estas melhorias.
