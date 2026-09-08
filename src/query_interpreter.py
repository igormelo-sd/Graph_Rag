"""
Query Interpreter — analisa a pergunta e determina:
  - quais fontes de dados consultar (text / tables / timeseries)
  - versão reescrita da query para melhor recuperação
  - (deep search) queries alternativas/decompostas e HyDE opcional
"""
import json
import os
from src.labor_market_skill import is_labor_market_query

INTERPRET_PROMPT = """\
Você é um roteador de consultas para um sistema RAG de dados econômicos do Estado de São Paulo.

Analise a pergunta e determine:
1. Quais fontes de dados são necessárias para responder
2. Uma versão reescrita da pergunta para maximizar a precisão na recuperação

Fontes disponíveis:
- "text": trechos narrativos dos boletins (análises, comentários, contexto qualitativo)
- "tables": tabelas com dados estáticos ou comparativos (valores pontuais, rankings, comparações entre regiões/setores)
- "timeseries": séries temporais (evolução mensal/trimestral, tendências, crescimento, variação ao longo do tempo)
- "image": gráficos rasterizados extraídos via visão (quando RAG_VISION=1; use quando a resposta pode depender de gráfico escaneado sem tabela textual)
- "graph": grafo de conhecimento — relações entre indicadores, setores, regiões e fontes de dados

Regras de seleção:
- Inclua "text" para qualquer pergunta que precise de contexto narrativo ou analítico
- Inclua "tables" se a pergunta busca valores específicos, rankings ou comparações pontuais
- Inclua "timeseries" se a pergunta envolve evolução, tendência, crescimento, variação temporal ou sequência de períodos
- Inclua "image" se RAG_VISION=1 e a pergunta pode depender de gráfico/figura sem tabela textual correspondente (ex: distribuição, mapa, pizza)
- Inclua "graph" se a pergunta envolve relações entre múltiplos indicadores, comparações entre setores/regiões, causalidade ou correlação entre variáveis econômicas
- Expanda siglas na reescrita (ex: PIB → Produto Interno Bruto, PNAD, IPCA)
- Seja específico sobre períodos, setores e indicadores na reescrita

Responda SOMENTE com JSON válido (sem markdown, sem texto extra):
{{"sources": ["text"], "rewritten_query": "versão reescrita da pergunta"}}

Pergunta: {question}
"""

DEEP_INTERPRET_PROMPT = """\
Você é um roteador de consultas para um sistema RAG de dados econômicos do Estado de São Paulo.

Analise a pergunta e determine fontes, reescrita e decomposição para deep search.

Fontes: "text", "tables", "timeseries", "image", "graph" (mesmas regras acima).
Decomponha a pergunta em 2-3 queries alternativas que cubram ângulos diferentes
(sinônimos, períodos, setores correlatos — ex: "desemprego" → "taxa de desocupação", "PNAD", "Caged").

Responda SOMENTE com JSON válido:
{{"sources": ["text", "timeseries"], "rewritten_query": "versão principal reescrita", "rewritten_queries": ["alt 1", "alt 2"]}}

Pergunta: {question}
"""

_VALID_SOURCES = {"text", "tables", "timeseries", "image", "graph"}


def _deep_search_enabled() -> bool:
    return os.getenv("RAG_DEEP_SEARCH", "0").strip().lower() in {"1", "true", "yes", "on"}


def interpret_query(question: str, llm) -> dict:
    """
    Interpreta a query e retorna:
        {"sources": [...], "rewritten_query": "...", "rewritten_queries": [...]}

    Sempre retorna ao menos "text" em sources como fallback seguro.
    Quando RAG_DEEP_SEARCH=1, também retorna alternativas para deep search.
    """
    prompt = DEEP_INTERPRET_PROMPT.format(question=question) if _deep_search_enabled() else INTERPRET_PROMPT.format(question=question)
    raw = llm.complete(prompt).text.strip()

    # Remove markdown code fences, se presentes
    raw = raw.strip("` \n")
    if raw.startswith("json"):
        raw = raw[4:].strip()

    try:
        result = json.loads(raw)
        sources = [s for s in result.get("sources", []) if s in _VALID_SOURCES]
        # Visão off → remove image para não quebrar retrieval sem índice
        if os.getenv("RAG_VISION", "0").strip().lower() not in {"1", "true", "yes", "on"}:
            sources = [s for s in sources if s != "image"]
        if "text" not in sources:
            sources = ["text"] + sources
        rewritten = result.get("rewritten_query", question) or question
        alt = result.get("rewritten_queries") if isinstance(result.get("rewritten_queries"), list) else []
        # filtra strings válidas e limita a 3
        alt = [str(q).strip() for q in alt if isinstance(q, str) and str(q).strip()][:3]
        return {
            "sources": sources or ["text"],
            "rewritten_query": rewritten,
            "rewritten_queries": [rewritten] + alt if alt else [rewritten],
            "is_labor_market": is_labor_market_query(question),
        }
    except (json.JSONDecodeError, AttributeError):
        return {
            "sources": ["text"],
            "rewritten_query": question,
            "rewritten_queries": [question],
            "is_labor_market": is_labor_market_query(question),
        }
