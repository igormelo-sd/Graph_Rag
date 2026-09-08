# .agents/ — LLM Factory e skills compartilhadas

> Leia primeiro `../AGENTS.md`. Este diretório é **copiado para dentro das 5
> imagens** no `docker/Dockerfile` (linhas 32–36). Qualquer mudança aqui exige
> **rebuild** das imagens (não basta `start_docker.bat` normal; use `--rebuild`).

## Papel

Camada única de acesso a LLMs/providers (a "fábrica de LLMs") + a skill de
análise de mercado de trabalho. É o ponto central onde endereços, chaves,
modelos e provisão de provider são resolvidos — as engines/orquestrador importam
isto e **nunca** criam `OpenAI(api_key=...)` solto.

## Arquivos-chave

- `llm_factory.py` — API principal: `llm_factory.get_llm(filters,...)` e o
  alias de módulo `llm_factory`. Decide provider a partir de env e devolve um
  objeto compatível (`_OpenAICompat` — llama_index-compatible, override de
  `.metadata`, hea context 8000, chat). Também `get_async_client()` e
  `LLMKeyNotFoundError`.
  - Endpoints atuais: Maritaca **`https://chat.maritaca.ai/api`**, OpenAI
    `https://api.openai.com/v1`, OpenRouter `https://openrouter.ai/api/v1`.
  - Usa o parâmetro **`api_base`** do construtor OpenAI (não `base_url`).
  - Fallback de chaves e módulos por provider.
- `skills/labor_market_analysis/SKILL.md` — skill de análise de indicadores do
  mercado de trabalho (exemplos + recursos internos). Referenciada pelo agente;
  não roda em produção.

## Mudanças comuns

- **Trocar provider/modelo/endpoint padrão**: `llm_factory.py` (e `.env`).
- **Adicionar um provedor**: novo bloco de resolução + endpoint + chave em
  `llm_factory.py`.
- **Ajustar skill analítica**: `skills/labor_market_analysis/*`.

## Armadilhas

- **Rebuild obrigatório** após qualquer mudança (`.agents/` entra no Dockerfile).
- Nunca importe `llm_factory` sem o `sys.path` das variantes — os `main.py` de
  cada `rag_*/` adicionam `.agents/` ao path.
- Não recrie `OpenAI(api_key=...)` no código das engines — use a factory (evita
  o bug de endpoint/401 já ocorrido).
- `__pycache__/` — gerado; não versionar.

## Comandos

```powershell
# teste local da factory (fora do Docker), com .env carregado:
python -c "import sys; sys.path.insert(0, '.agents'); from llm_factory import llm_factory; print(llm_factory.get_llm())"
# após alterar llm_factory.py:
docker compose -f docker/docker-compose.yml build --no-cache rag-principal
docker compose -f docker/docker-compose.yml up -d rag-principal
```