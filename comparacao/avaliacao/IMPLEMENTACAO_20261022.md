# Melhorias implementadas em 22/10/2026

As cinco melhorias propostas foram implementadas na aplicação GraphRAG.

| Melhoria | Resultado |
|---|---|
| Busca tabular | Consulta CSV/XLSX/XLS completos por códigos, município, ano, trimestre, aba e células; preserva cabeçalhos, notas e localização da linha. |
| Validação numérica | Vínculo narrativo por ocorrência com território, período, comparação e direção; mantém rejeições de coincidências sem contexto. |
| Qualidade da geração | Detecta rótulos isolados de classificação, corrupção e mistura evidente de idiomas; permite uma regeneração, preservando fontes. |
| Esclarecimentos | A série “PIB paulista” identifica o estado; São Paulo genérico continua exigindo esclarecimento. |
| Avaliação | Modelo fixo obrigatório, manifesto, identificação reportada do modelo, ficha por ponto obrigatório e quatro notas separadas da rubrica. |

## Verificações executadas

- **319 testes locais passaram**, cobrindo GraphRAG, módulos compartilhados e comparação. Há um aviso do openpyxl sobre área de impressão, sem falha de leitura das células verificadas.
- As **20 perguntas de desenvolvimento e suas 31 referências** passaram pela conferência de integridade documental. Isso não equivale a revisão semântica humana.
- Na resposta histórica D007, o novo validador reconheceu **2,3%, 2025 e 1,6%**, vinculando as taxas a dezembro e novembro de 2025. Os testes negativos abrangem território, município versus estado, mês, direção e base de comparação diferentes.
- O teste no corpus confirmou a recuperação da linha **38057** do PIB municipal, fora do antigo corte da ingestão vetorial, e da célula **Tabela 3!O105**, com sua nota de dados preliminares.

Comando da suíte:

```powershell
.\.venv\Scripts\python.exe -m pytest graphrag/tests tests_shared comparacao/tests -q --capture=sys
```

## Coleta no aplicativo completo

Modelo local fixo: **qwen3:4b-instruct**, com digest registrado no manifesto.
Orçamento de evidências de 1000 tokens estimados, saída máxima de 400 tokens e
reranking BGE desativado somente nesse processo. O contexto menor permitiu usar
a janela de 4096 tokens do servidor local, que recusou a primeira síntese com
o orçamento maior. As configurações permanentes do aplicativo foram preservadas.

| Pergunta | Execução | Conteúdo central observado |
|---|---|---|
| D004 | Sem erro técnico | CNAE 47.32-6: Comércio varejista de lubrificantes; fonte cnae20.csv, registro 416. |
| D005 | Sem erro técnico | DRS Campinas; fonte codigos_municipios_regioes.csv, registro 112. |
| D011 | Sem erro técnico | Adamantina, IBGE 3500105, PIB de 2018 de R$ 1.070.909.946; fontes municipais nos registros 4 e 38057. |

As três respostas reportaram o mesmo modelo configurado. O manifesto confirmou
corpus, código e perguntas inalterados durante a rodada e coleta completa dos
três casos. A D011 também gerou explicações adicionais: a qualidade de toda a
redação permanece para avaliação pela rubrica, sem aprovação automática.

Resultados: [coleta com contexto de 1000 tokens](../artefatos/resultados/melhorias_20261022_contexto1000/manifesto.json).
As tentativas locais anteriores foram preservadas para diagnóstico; a primeira
também registrou alteração do código durante sua execução e não serve como
rodada congelada. Não houve nova execução das 20 perguntas completas nem do
conjunto reservado de 100 perguntas nesta implementação.

## Revisão dos gabaritos

D012 agora explicita a comparação com novembro e o ajuste sazonal, removendo a
ambiguidade da pergunta. D009 recebeu somente um ajuste de espaço no trecho
literal extraído. Os resultados históricos devem continuar associados à versão
anterior do banco, identificada por seu hash.

Foi preparada uma [ficha das 20 perguntas](../artefatos/resultados/melhorias_20261022_auditoria/revisao_20_perguntas.json),
com pontos obrigatórios e notas separadas para correção, apoio documental,
completude e qualificação. Os gabaritos continuam **pendentes de revisão humana**.

A checagem global encontrou um trecho não confirmado literalmente no conjunto
reservado, em **pmc_202512caderno.pdf, página PDF 29**. A conferência geral desse
conjunto permanece bloqueada nessa referência para revisão independente; o
arquivo de perguntas de teste não foi alterado.

As validações numérica e de idioma continuam heurísticas. Esta coleta de três
casos verifica a aplicação completa e não substitui o experimento controlado
entre RAG simples e GraphRAG. Consulte [as instruções de avaliação](README.md)
para congelamento, coleta e revisão.

## Extensão ao RAG principal

As cinco melhorias também foram integradas ao aplicativo principal (`main.py`):
busca tabular completa, vínculo numérico contextual, regeneração limitada de
saídas inválidas, interpretação de “PIB paulista” e avaliação com modelo fixo.
As fontes HTTP do principal também incluem linha, aba e células; o uso registra
identidades de modelo reportadas pelo provedor.

A busca literal e o vínculo numérico estão em `rag_app`, com entradas de
compatibilidade nas duas pastas `src`. As engines e os startups permanecem
separados. O principal conserva a recuperação híbrida e seu grafo opcional já
existente; expansão por pais e busca global por comunidades continuam na
variante GraphRAG. O RAG mínimo experimental e o protocolo controlado de
`comparacao/run.py` não receberam estratégias adicionais de recuperação.

O coletor agora aceita `--versao principal` e `--versao graphrag`, resolve o
corpus efetivo de cada aplicação, respeita o interpretador próprio da versão
e recusa a mistura de módulos de implementações diferentes no mesmo processo.
Veja [os comandos de coleta](README.md).

Na verificação em processos separados passaram as suítes compartilhada
(36 testes), principal (238), GraphRAG (263), RAG mínimo (6) e comparação (20).
Após adicionar a verificação do coletor principal, os 37 testes do arquivo de
regressões do principal passaram, incluindo esse caso adicional. Foram usados
modelos simulados: não houve nova rodada de perguntas com modelo real do
principal, nem reconstrução dos índices de produção nesta extensão.
