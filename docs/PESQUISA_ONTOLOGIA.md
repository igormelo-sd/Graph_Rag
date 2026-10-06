# Ontologia em tecnologia e IA: significado e atuação no Graph_Rag

Pesquisa realizada em 5 de outubro de 2026. A análise do projeto é estática: nenhum teste, servidor, extrator ou avaliação foi executado. As quatro propostas anteriores são preservadas abaixo, com ajustes conceituais. Este documento não implementa essas propostas.

Atualização posterior: as quatro frentes receberam implementação inicial no código, descrita em [ONTOLOGIA.md](ONTOLOGIA.md). O diagnóstico abaixo registra o estado anterior às mudanças, incluindo o acoplamento antigo das flags. As novas funcionalidades e seus ganhos continuam sem teste ou avaliação; as referências conceituais permanecem aplicáveis.

## 1. Definição e alcance

Na computação, uma ontologia explicita como um domínio é concebido: quais conceitos são relevantes, quais propriedades e relações existem e qual significado essas representações têm. Gruber apresentou a definição clássica de especificação explícita de uma conceitualização no contexto de compartilhamento de conhecimento entre sistemas de IA. [Gruber, 1993](https://tomgruber.org/writing/ontolingua-kaj-1993/).

Seu verbete de 2009 esclarece que essa especificação pertence ao nível semântico, acima das escolhas de armazenamento. Também reconhece usos com diferentes graus de expressividade, de glossários operacionais a teorias lógicas. Assim, OWL, RDF, um reasoner ou uma hierarquia extensa não são requisitos universais para usar o termo; a questão é o significado explicitado e o compromisso dos sistemas com ele. [Gruber, 2009](https://tomgruber.org/writing/definition-of-ontology.pdf).

Para este projeto, a pergunta relevante é: o modelo distingue e conecta os conceitos necessários para responder perguntas econômicas de maneira coerente? Acrescentar categorias sem definições e sem uso efetivo não resolve esse problema.

## 2. Conceitos próximos, mas com funções diferentes

| Elemento | Função no contexto do projeto |
|---|---|
| Vocabulário controlado | Padronizar termos e nomes utilizados |
| Taxonomia | Organizar categorias em hierarquias |
| Esquema de dados | Definir a estrutura aceita pela representação |
| Ontologia | Explicitar conceitos, significados e relações do domínio |
| Grafo de conhecimento | Representar entidades e afirmações concretas conectadas |
| Validador | Conferir dados contra regras de conformidade |

Essa tabela é uma síntese operacional, não uma divisão universal rígida: os artefatos podem se sobrepor. SKOS, por exemplo, representa conceitos, rótulos preferidos e alternativos e relações hierárquicas; pode ser combinado com OWL para necessidades mais formais. [W3C, SKOS Primer](https://www.w3.org/TR/skos-primer/).

Em OWL, classes, indivíduos e propriedades têm papéis explícitos. Uma classe territorial não é a mesma coisa que um território concreto; uma regra de subclasse precisa estar declarada para ser usada pelo raciocínio formal. O nome de uma categoria sozinho não fornece essa regra. [W3C, OWL 2 Primer](https://www.w3.org/TR/owl2-primer/).

Aplicação proposta: `Territorio` seria uma classe; o Estado de São Paulo, uma entidade; uma observação de um indicador num período, outra entidade. A ontologia especificaria como essas entidades podem se relacionar; o grafo armazenaria as observações efetivamente extraídas.

## 3. Raciocínio lógico e validação não são intercambiáveis

OWL permite declarar relações e axiomas dos quais um reasoner pode derivar consequências. Trabalha com hipótese de mundo aberto: uma informação ausente não é automaticamente falsa. Declarações de domínio e alcance de propriedades podem produzir inferências de tipo; não equivalem, por si só, a rejeitar registros incompletos. [W3C, OWL 2 Primer](https://www.w3.org/TR/owl2-primer/).

SHACL é um padrão específico para descrever e validar grafos RDF, incluindo tipos, cardinalidades e outras restrições, produzindo relatórios de conformidade. [W3C, SHACL](https://www.w3.org/TR/shacl/).

Conclusão para o Graph_Rag: mantenha definições semânticas e regras de validação explicitamente relacionadas, mas reconheça suas funções distintas. Pode-se começar com um modelo declarativo e validação em Python. Isso não seria uma implementação de SHACL nem de raciocínio OWL; uma futura exportação RDF poderia facilitar interoperabilidade, se ela for um objetivo do trabalho.

## 4. Representar dados econômicos como observações

O RDF Data Cube organiza dados estatísticos em observações, dimensões, medidas e atributos. Período e território podem identificar o recorte; a medida representa o fenômeno observado; atributos qualificam valores com unidade, escala ou status. O modelo distingue ainda metadados de estrutura e do conjunto de dados. [W3C, RDF Data Cube, seções 5.1–5.2](https://www.w3.org/TR/2014/REC-vocab-data-cube-20140116/#data-cubes).

Esse padrão sustenta a proposta de uma entidade `ObservacaoEstatistica`. Não obriga o aplicativo a trocar imediatamente seu armazenamento por RDF.

Exemplo de estrutura proposta, sem valores reais:

```text
ObservacaoEstatistica
  indicador: indicador identificado
  valor: valor extraído
  unidade e escala: conforme a fonte
  periodo: intervalo de referência
  territorio: entidade identificada
  setor: quando aplicável
  cobertura e metodologia: quando disponíveis
  proveniencia: documento, página e trecho/célula
```

Uma afirmação de crescimento entre períodos poderia ser representada como comparação entre observações, com fórmula e base de comparação. Isso é mais preciso do que atribuir crescimento ao conceito genérico `Emprego`. Campos ausentes devem permanecer identificados como ausentes; o modelo não deve inventar dimensões obrigatórias para completar um registro.

## 5. Papel possível junto a um LLM

As funções abaixo são propostas de arquitetura para este código, não resultados experimentais:

1. Orientar extração com definições e exemplos de conceitos.
2. Resolver termos e entidades por identificadores e aliases controlados.
3. Representar os dados extraídos preservando recortes e proveniência.
4. Selecionar observações compatíveis com as dimensões da pergunta.
5. Validar registros e comparações antes de alimentar cálculos e síntese.

O LLM pode propor classificações e relações, mas sua saída continua sendo uma hipótese de extração. Conformidade estrutural não demonstra que o valor foi lido corretamente ou que a fonte sustenta a afirmação. Verificação documental e avaliação humana continuam necessárias.

## 6. O que o código atual faz

| Trecho | Atuação observada | Limitação |
|---|---|---|
| [graph_ontology.py](../src/graph_ontology.py), `_FIXED_TYPES` | Lista nove categorias | Não fornece definições operacionais por categoria |
| `_sample_chunks` e `discover_entity_types` | Amostra até seis trechos e propõe até quatro tipos | Não avalia cobertura por tema/documento ou utilidade nas consultas |
| Saída `cleaned` | Retorna nomes dos tipos | Descrições ficam no registro bruto, sem alimentar o extrator |
| [graph_indexing.py](../src/graph_indexing.py), listas de tipos | Fornece entidades e relações ao `DynamicLLMPathExtractor` | Não declara uma matriz semântica de combinações válidas ou uma camada própria de validação dessas combinações |
| [graph_retriever.py](../src/graph_retriever.py) | Expande termos com LLM e consulta caminhos | Não recebe diretamente as definições da ontologia para planejar a consulta |
| `retrieve_neighbors` | Anexa vizinhos por metadados BM25 | A costura não é raciocínio ontológico |
| [evidence.py](../src/evidence.py) | Reconhece dimensões com padrões próprios | Não compartilha um modelo declarativo com os tipos do grafo |

Minha classificação: existe um vocabulário de domínio e um esquema inicial de extração com função ontológica limitada. É defensável chamá-lo de ontologia leve ou incipiente, desde que o TCC explicite sua expressividade e não atribua inferência formal, validação semântica ou ganho medido que não estão presentes.

### Acoplamento de configuração identificado

Em `graph_indexing.py`, `graph_config['llm']` considera `use_llm`, embedding do grafo e descoberta de ontologia. Quando o grafo é inicializado, habilitar embedding ou descoberta também seleciona o caminho de extração por LLM. Em `startup.py`, a flag de descoberta sozinha não participa da condição de inicialização; com estrutura, embedding e grafo LLM desligados, ela não inicia o grafo.

Isso corrige uma simplificação da documentação anterior: as flags representam intenções distintas, mas os caminhos de execução ainda são acoplados. A descoberta não corresponde necessariamente a apenas uma chamada adicional sem extração subsequente. Nenhuma configuração foi executada para medir esse efeito.

## 7. Sugestões preservadas e refinadas

1. **Observações estatísticas:** representar valor, indicador, unidade, escala, período, território, recortes aplicáveis e proveniência. Distinguir estoque, fluxo, saldo, taxa e variação segundo as definições das fontes.
2. **Relações tipadas:** definir significado, origem e destino esperados; implementar separadamente verificações de conformidade e completude. Não prometer raciocínio formal apenas por ter regras Python.
3. **Normalização de entidades:** manter identificadores, aliases e hierarquias pertinentes. Resolver “São Paulo” pelo contexto, sem equiparar automaticamente estado e município; relações hierárquicas não são equivalências.
4. **Uso na consulta:** compartilhar o modelo entre extração, busca, cálculo e evidências para selecionar dados comparáveis e sinalizar ambiguidades. Descoberta automática de tipos deve propor extensões revisáveis, em vez de alterar silenciosamente o modelo.

Antes de implementar, delimite as perguntas que a ontologia deverá permitir responder. Noy e McGuinness recomendam definir domínio, escopo e perguntas de competência, além de considerar reutilização de modelos existentes. [Stanford, Ontology Development 101](https://protege.stanford.edu/publications/ontology_development/ontology101-noy-mcguinness.html).

Perguntas de competência propostas:

- Duas observações se referem ao mesmo indicador e recorte territorial?
- Os períodos, unidades e bases de comparação permitem a operação solicitada?
- A entidade “São Paulo” representa estado, município ou outro recorte nesta fonte?
- Qual trecho ou célula sustenta cada operando de um cálculo?
- O dado é nível, saldo ou variação, e essa distinção foi preservada?

Essas perguntas podem orientar uma avaliação futura. Não há evidência atual de que enriquecer a ontologia, sozinho, melhore as respostas: esse benefício precisa ser medido separadamente da qualidade da extração.
