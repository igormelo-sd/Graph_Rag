# Diagnóstico do log de inicialização e consultas

O log fornecido mostra a criação de 27.091 nós, a conclusão dos embeddings e a
promoção da coleção, seguida da construção do grafo e da mensagem “Sistema pronto”.
Os embeddings foram registrados entre 13:13:03 e 15:24:50. Houve reconstrução
completa porque o fingerprint do pipeline havia mudado.

Os avisos de ausência de tabelas do Camelot, de área de impressão do Excel e de
fonte do desenho do grafo não interromperam essa execução. A presença desses
avisos não demonstra que todas as tabelas foram extraídas corretamente; isso exige
conferência de conteúdo. A inspeção anterior dos PDFs está em
`comparacao/avaliacao/filtro_pdfs.md`.

## Consulta de PIB

Na consulta “Qual é o pib de campinas?”, o roteador selecionou somente `text` e
as referências retornadas foram PDFs narrativos e metodológicos. Essa seleção
excluiu os retrievers de tabelas. Além disso, a pergunta não define ano nem
esclarece se pretende município ou região de Campinas.

Correções aplicadas:

- Pedido pontual de PIB inclui `tables`, mesmo com JSON inválido ou uma seleção
  incompleta do roteador. Isso não substitui conferir os valores recuperados.
- Pedido pontual sem ano pede o período antes de chamar o modelo ou os retrievers.
- A interface de terminal apresenta esse pedido de esclarecimento diretamente.
- Perguntas conceituais e pedidos expressos de dado mais recente não recebem o
  bloqueio de período. Pedidos de dados recentes continuam sujeitos à cobertura
  e à qualidade da recuperação.
- As consultas alternativas produzidas pelo interpretador também chegam à engine
  no terminal, como já acontece no serviço HTTP.

Exemplos com recorte definido:

```text
Qual é o PIB do município de Campinas em 2020, em reais?
Qual é o PIB da Região Administrativa de Campinas em 2025, em bilhões de reais?
```

## Pergunta ampla sobre a economia paulista

A segunda consulta recuperou tabelas e trechos, mas o modelo retornou uma recusa.
A extração de série temporal registrou resposta estruturada vazia e acionou o
fallback narrativo. O log não contém o contexto completo nem a resposta bruta
necessários para atribuir essa recusa a uma causa única.

As regras de roteamento foram verificadas com modelos simulados, sem reconstrução
do índice ou execução de embeddings.

## Teste real autorizado e resposta vazia

Após autorização explícita, foram enviados dois trechos do cache existente ao
provedor configurado, OpenRouter, com o identificador `openrouter/free`: PIM
regional, página PDF 9, e metodologia do Seade, página PDF 20. Não foi executada
a inicialização completa nem a recuperação híbrida nesse teste de síntese.

Com o limite original de 1.200 tokens, a resposta real tinha zero caracteres.
O sanitizador convertia esse resultado em mensagem de ausência de evidência.
Essa conversão mascarava uma falha de geração.

Repetindo com os mesmos trechos e limite de 4.096 tokens, o provedor devolveu
texto, com término `stop` e uso reportado de 1.249 tokens de conclusão, dos quais
1.049 eram de raciocínio. Os arquivos `.env` da raiz e de `graphrag` passaram a
definir `RAG_MAX_OUTPUT_TOKENS=4096` para o chat. O perfil experimental de
`comparacao/config.json` não foi alterado.

O identificador é um roteador, portanto essa comparação de duas chamadas não
garante o mesmo modelo subjacente e não prova que o limite seja a única causa.
Ela confirma que houve uma resposta vazia e que o segundo teste gerou texto.

Agora a factory e a engine rejeitam resposta vazia com `EmptyModelResponse`, sem
trocar automaticamente de provedor. O terminal mostra uma falha de geração; a API
retorna HTTP 502. O prompt de síntese também explicita que perguntas amplas podem
receber respostas parciais sustentadas, com períodos e territórios identificados.

Os relatórios técnicos ficam em `comparacao/artefatos/diagnostico/`. Gerar texto
não significa que a resposta seja semanticamente correta: a amostra real misturou
uma descrição de média móvel nacional com a narrativa paulista. Esse resultado
não foi promovido a gabarito nem considerado prova de qualidade do RAG. A consulta
completa continua sujeita à validação documental e numérica.

## Aplicação no chat

Feche o processo antigo e abra novamente `graphrag/start.bat` para carregar código
e configuração atualizados. O fingerprint do processamento não mudou nestes
ajustes; eles não exigem reconstruir os embeddings.
