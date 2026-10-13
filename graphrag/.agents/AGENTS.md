# .agents/ — skills e helper legado

Leia primeiro [AGENTS.md](../AGENTS.md). Este repositório é independente; não pressupõe Docker, cinco imagens ou variantes em diretórios superiores.

## Uso pelo aplicativo

`src/llm.py` é a factory do fluxo principal. `llm_factory.py` neste diretório é um helper legado separado; suas regras de fallback não descrevem o comportamento do aplicativo atual. Ajuste o provedor principal pela configuração documentada no README e por `src/llm.py` quando necessário.

`src/domain_skills.py` registra skills com `rag-routing.json` e injeta na síntese o conteúdo entre `<!-- rag-context:start -->` e `<!-- rag-context:end -->` do `SKILL.md`. Assim, partes das skills de domínio são instruções de produção. Referências e scripts auxiliares não são carregados ou executados automaticamente por esse registro.

## Ao editar skills

Preserve frontmatter, roteamento, marcadores e títulos consumidos pelos leitores. Limite interpretações econômicas às evidências recuperadas. Não obrigue a resposta a preencher dimensões ausentes nem suprima limitações necessárias para comparar números.

Exemplos de código e mapeamentos em recursos são materiais auxiliares: precisam ser adaptados ao esquema e à versão da fonte antes do uso. Não trate referências metodológicas como dados recuperados do corpus.

Leia a skill inteira antes de alterar regras. Respeite instruções explícitas de não executar testes ou validadores. Mudanças de prompt não representam resultados de avaliação. `__pycache__/` é gerado e não deve ser versionado.
