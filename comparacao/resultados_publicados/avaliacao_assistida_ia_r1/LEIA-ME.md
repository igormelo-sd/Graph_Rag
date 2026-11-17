# Registro da avaliação assistida

Rodada: v4b_teste_20261113_r1. Data: 17/11/2026. Avaliador: ChatGPT (IA).

Foram lidas 150 respostas, correspondentes às mesmas 50 perguntas para os três RAGs da rodada. Cada resposta recebeu quatro notas de 0 a 2 (correção, apoio documental, completude e qualificação), evidências para os pontos obrigatórios e classificação da recuperação. A avaliação é assistida por IA e requer revisão humana antes de uso como resultado experimental definitivo.

## Arquivos

- `ficha.html`: abre preenchida, permite revisão e exportação/importação; inclui trechos extraídos diretamente dos documentos originais para auditoria.
- `ficha_preenchida_150.json`: avaliações estruturadas com rótulos A/B/C e identificador da nova ficha.
- `_chave/chave.json`: correspondência dos rótulos aos RAGs. Consultar apenas depois da avaliação.
- `corpus_verificado.json`: comparação SHA-256 dos 20 arquivos originais com o corpus registrado na rodada; nenhuma divergência.

A ficha original continha apenas A/B. A nova ficha tem identificador próprio para evitar colisão com avaliações já salvas no navegador. O gerador e pontuador original `cega.py` são limitados a dois sistemas: este JSON não deve ser passado a eles sem adaptação para três rótulos. Não foram alterados o código do experimento, o banco congelado de perguntas nem os resultados dos RAGs. Não houve novas chamadas aos modelos dos RAGs.

## Critérios aplicados

A rubrica usada foi `comparacao/avaliacao/rubrica.md`. As notas foram atribuídas por leitura semântica, não por coincidência de palavras. O marcador “não” em um ponto composto indica que pelo menos uma parte relevante faltou; a completude pode ser 1 por atendimento parcial. A descrição da evidência é paráfrase do avaliador. A ausência de uma soma ou inferência causal indevida atende aos respectivos cuidados sem exigir uma frase literal.

Uma abstenção em pergunta respondível recebe penalidade em correção/completude; pode manter apoio parcial quando descreve fielmente os limites dos trechos recebidos. Apoio documental avalia a resposta efetiva e suas citações, enquanto recuperação considera o contexto disponível nos resultados, inclusive fontes não citadas. “Sim” em recuperação não significa suficiência semântica universal: T097 exemplifica evidência disponível com leitura incorreta de coluna.

Os PDFs foram consultados por páginas; a Tabela 1 da PIM regional também foi renderizada e inspecionada para confirmar o traço do Maranhão. Planilhas foram lidas diretamente por células, cabeçalhos e notas, e CSVs com sua codificação e registros correspondentes. A identidade anual T070 foi recalculada com os valores originais: 2.943.727,66530395 + 501.086,36763772 = 3.444.814,03294167 milhões de reais. Não se tomaram gabaritos, validadores ou números recuperados como prova automática de correção.

## Ajustes dos gabaritos

- T059: “indústria” não especifica produção física. Aceita-se também PIB 2,3% versus VA industrial 1,4%, quando esse conceito é explícito, sustentado pela página PDF 13 das Contas Nacionais. A leitura PIM-PF continua sendo 0,6%.
- T072: “em dezembro” não especifica a comparação. Aceita-se a alternativa interanual explicitamente identificada (SP -3,2%, Brasil +0,4%), além da mensal ajustada (SP -1,6%, Brasil -1,2%).
- T024: conteúdo mantido; o registro de dados 429 é a linha física 430 do CSV com cabeçalho.

Esses ajustes constam da revisão de cada pergunta; o texto do gabarito congelado permanece visível. Uma revisão humana pode optar por manter a interpretação estrita e repontuar esses casos, com registro dessa decisão.

## Cegamento e limites

As três respostas foram novamente sorteadas entre A/B/C por pergunta, e a chave não foi consultada durante a atribuição de notas. Na exploração preliminar, antes do sorteio, foi lida a resposta T002 identificada como lexical_rag. Portanto, T002 não tem cegamento estrito garantido. Os textos não foram reescritos, e semelhanças entre respostas também podem permitir reconhecimento. Não se reivindica avaliação humana independente nem cegamento absoluto.

Não foram calculados rankings ou significância estatística. As 150 respostas correspondem a 50 perguntas, não a 150 perguntas independentes. A conclusão de ausência de PIB por bairro é limitada ao corpus inspecionado e sua granularidade territorial.

## Colocação no caminho solicitado

A sessão tinha leitura, mas não permissão de gravação em `C:\Users\Igormelo\Graph_Rag_v4`. Por isso a ficha original não foi sobrescrita. Para usar a nova versão, preserve uma cópia da pasta original e coloque o conteúdo deste pacote em uma nova pasta de avaliação. Abra `ficha.html`; não é necessário importar o JSON para visualizar as notas. A chave de três sistemas acompanha esta ficha e não deve ser confundida com a chave A/B anterior.

## Verificação da entrega

Sintaxe JavaScript, 50/50 perguntas completas, 150 blocos de resposta, 600 notas, reconhecimento de nota zero e igualdade dos dados após exportação/importação verificados em execução com DOM simulado. A inicialização de um navegador local falhou e a prévia de arquivo local foi bloqueada pela política do navegador; não foi possível validar visualmente o HTML.
