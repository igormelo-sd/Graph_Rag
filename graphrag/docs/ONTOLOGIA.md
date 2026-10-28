# Ontologia de domínio no Graph_Rag

O modelo declarativo de `src/domain_ontology.py` compartilha conceitos e dimensões entre ingestão, busca, interpretação, cálculos e evidências. Atua com ou sem embedding de grafos. Fundamentação: [PESQUISA_ONTOLOGIA.md](PESQUISA_ONTOLOGIA.md); referências: [TCC.md](TCC.md).

## Conceitos e observações

O vocabulário distingue indicador, observação estatística, comparação, território, região, estado, município, setor, período, unidade, fonte e entidades documentais. Estado, município e região são especializações de território. O cadastro inicial cobre Brasil, Estado de São Paulo, Município de São Paulo, RMSP e Interior paulista; não é um cadastro territorial completo. Outros territórios, indicadores e setores entram por extensões revisadas (ver abaixo); nenhum cadastro adicional acompanha o repositório.

Cada observação candidata mantém valor literal, dimensões, arquivo, página, ID do chunk, posição e trecho de origem. A extração local é heurística: indicador, território, período ou unidade ausentes/múltiplos recebem `requires_review`. Mesmo `structured_candidate` não significa fato verificado. São Paulo sem qualificação permanece ambíguo; ano, mês e trimestre recebem representações distintas.

Dimensões e observações são anotadas nos metadados dos nós. Seu JSON é excluído do texto de embeddings e prompts. Aliases reconhecidos alimentam expansão controlada de consultas.

A versão `economic-observations-v2` preserva cabeçalhos, linhas, título/notas literais e proveniência por célula. Datas de publicação são atributos separados. Consultas ambíguas sobre São Paulo pedem esclarecimento antes da síntese. Relações registram modalidade, polaridade e origem, com controles de causalidade. Cobertura, divergências, hierarquias e grafos de derivação estão descritos em [ESTATISTICAS_GRAFO.md](ESTATISTICAS_GRAFO.md).

## Relações e aplicação no fluxo

`src/ontology_extractor.py` solicita triplas JSON com classes, relação e citação literal. Confere formato, nomes e trecho de apoio, resolve cada entidade no cadastro (o tipo territorial cadastrado prevalece sobre o rótulo do LLM; períodos viram a forma normalizada, como `2023-Q2`) e só então valida domínio e alcance. `CRESCEU_EM` e `RECUOU_EM` ligam `Indicador` a `Período`; `Comparacao` existe apenas no grafo de cálculo da consulta. Registra aceitação e rejeição em auditoria. Conformidade e presença literal não provam a interpretação semântica do LLM.

| Etapa | Implementação |
|---|---|
| Ingestão e índice | Dimensões, observações, versão e hash nos metadados |
| Interpretação | Definições no prompt; proteção da reescrita; inclusão da fonte grafo para perguntas com indicador, território e período reconhecidos |
| Busca | Expansão de aliases e filtro posterior de conflitos explícitos; preservação de candidatos incompletos |
| Grafo | Observações ligadas ao chunk real por `SUSTENTADA_POR`, dimensões únicas tipadas e hierarquia territorial cadastrada |
| Consulta ao grafo | Recuperação local por dimensões/hierarquia, travessia de arestas documentais e caminhos rastreáveis; LLM opcional |
| Tabelas e séries | Definições comuns nos prompts de extração e planejamento |
| Cálculos | Comparabilidade de indicador, território, unidade, natureza, escala, setor, fonte, base, cobertura e período |
| Síntese e evidências | Definições, observações, auditoria de divergências e grafos de cálculo; `ontology`, `knowledge` e `clarification` na API |

Diferença, variação percentual e pontos percentuais exigem períodos distintos, mesma granularidade e ordem base/final. Somar taxas, variações ou estoques não é autorizado automaticamente. Campos essenciais ausentes impedem a conta. Compatibilidade não comprova metodologia, agregabilidade ou completude da fonte. `Comparacao` define o contrato; cálculos de consultas não são gravados automaticamente como fatos no grafo.

## Configuração e revisão

- `RAG_ONTOLOGY_ENABLE=1` é o padrão: habilita anotação, observações, prompts e filtros. Desligá-lo mantém os contratos de extração tipada, proteção da reescrita e validação de evidências/cálculos.
- `RAG_ONTOLOGY_DISCOVER=1` inicia propostas por LLM, independentemente da extração de relações. Até doze amostras são selecionadas por rodízio entre documentos/modalidades; até quatro classes são propostas com definição, classe pai e trecho literal.
- Propostas ficam em `ontology.json` dentro de `RAG_GRAPH_DIR`, ou `graph_store/`. O cache considera corpus e modelo. Falhas não viram descoberta vazia válida; nova invocação pode tentar novamente.
- Somente extensões humanas com `reviewed: true` em `config/ontology_extensions.json` entram no modelo. `RAG_ONTOLOGY_EXTENSIONS` permite outro arquivo. Não edite o cache gerado para aprovar propostas; use `python scripts/review_ontology.py` para listar e `--approve Nome` para aprovar.
- O arquivo aceita quatro listas, todas revisadas item a item:
  - `entity_types`: `name` ASCII, `description` e `parent` existente;
  - `indicators`: `id`, `label`, `pattern` e `kind` opcional (`estoque`, `saldo`, `fluxo`, `taxa`, `variacao`);
  - `sectors`: `id`, `label`, `pattern` e `parent` opcional entre os setores cadastrados;
  - `territories`: `id`, `name`, `type` (`Estado`, `Municipio`, `Região` ou extensão deles), `parent` cadastrado e `pattern`.
- Padrões são expressões regulares aplicadas ao texto em minúsculas e sem acentos, e precisam ser escritos assim. Para municípios cujo nome é palavra comum, prefira padrões explícitos como `municipio de salto`. IDs repetidos, pais inexistentes e padrões inválidos interrompem a carga.
- O arquivo é relido quando muda; `python scripts/export_ontology_skos.py` gera `docs/ontologia.ttl` com classes, relações (`schema:domainIncludes`/`rangeIncludes`) e vocabulários SKOS, só para documentação.

O hash do modelo fica no manifesto (`pipeline.ontology_hash`), separado do fingerprint dos embeddings, e participa do cache do grafo. Como as anotações são excluídas do texto embutido, uma mudança só no esquema ou nas extensões não recalcula vetores: `reannotate_index` refaz as anotações no cache BM25 e nos metadados da coleção Chroma, e o grafo é reconstruído. Sem cache BM25, ou se a reanotação falhar, o índice é reconstruído por completo. A flag operacional de ativação não altera nenhum dos dois hashes; a avaliação desativa seu uso em consulta e preserva o mesmo corpus indexado.

## Limites e avaliação pendente

Este modelo em Python não implementa OWL, SHACL ou inferência lógica; a exportação Turtle é descritiva. Padrões têm cobertura limitada; tabelas complexas, números sem contexto e ambiguidades exigem revisão. Filtros podem remover contexto útil. Nenhum ganho experimental foi demonstrado.

Foram preparados casos em `tests/test_domain_ontology.py` e perguntas em `evaluation/ontology_cases.example.jsonl`. O harness combina três configurações com ativação/desativação parcial do modelo, totalizando seis modos. `competency_match` mede reconhecimento das dimensões da pergunta, não qualidade da resposta. Veja [CONFIABILIDADE.md](CONFIABILIDADE.md).

Os testes de `tests/test_graph_ontology_improvements.py` cobrem extensões, entidades canônicas, cache de extração e ordenação de observações. Nenhuma avaliação com gabarito foi executada.
