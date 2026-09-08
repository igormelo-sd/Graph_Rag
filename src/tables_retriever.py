"""
Tables Retriever — recupera dados de tabelas estáticas (não temporais) e os
estrutura via pandas para o Analysis Engine.

"Estática" = tabela com valores pontuais, rankings ou comparações entre categorias
(ex: emprego por setor, PIB por região). Distingue-se de TimeSeries pela granularidade.
"""
import re

from logger import get_logger
from runtime import limit_context
from text_retriever import rerank_candidate_limit, structured_top_n
from structured_output import (
    StructuredOutputError,
    parse_json_object,
    result_text,
    tabular_payload,
)

log = get_logger(__name__)
_FALLBACK_TOP_N = 3


def _sanitize(text: str) -> str:
    """Remove caracteres de controle inválidos que podem quebrar o JSON da API."""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

# Granularidades que indicam série temporal → excluídas deste retriever
_TEMPORAL_KEYWORDS = {
    "mensal", "trimestral", "semestral", "bimestral",
    "semanal", "diário", "diaria", "diária", "anual", "ano a ano",
}

# ── Prompts ───────────────────────────────────────────────────────────────────

_EXTRACT_PROMPT = """\
Você é um extrator de dados. Leia os trechos de tabelas abaixo e extraia os dados \
numéricos necessários para responder à pergunta.

Retorne SOMENTE um objeto JSON válido, sem markdown ou texto adicional.
Para dados tabulares, use:
{{"columns": ["Coluna 1", "Coluna 2"], "rows": [["valor", 1.2]]}}
Para poucos pares chave-valor, use:
{{"data": {{"chave": "valor"}}}}
Regras:
- Use apenas strings, números, booleanos ou null nas células.
- Não inclua código, comentários ou campos adicionais.
- Use nomes de colunas em português quando possível.

Trechos:
{context}

Pergunta: {question}
"""

_CALCULATE_PROMPT = """\
Você tem os dados estruturados abaixo. Calcule a resposta usando exclusivamente esses dados.
Retorne SOMENTE JSON válido no formato {{"resultado": "texto final"}}.
Regras:
- Não inclua código ou explicações fora do campo `resultado`.
- Formate números com separador de milhar e 2 casas decimais quando aplicável.
- Se a pergunta exigir uma conta, apresente a operação no texto final.

Pergunta: {question}

Dados disponíveis:
{data_preview}
"""

# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_static_table(node) -> bool:
    """True se o node for tabela com granularidade não-temporal."""
    if node.metadata.get("type") != "table":
        return False
    gran = str(node.metadata.get("table_granularidade") or "").lower()
    return not any(kw in gran for kw in _TEMPORAL_KEYWORDS)


# ── Retriever ─────────────────────────────────────────────────────────────────

class TablesRetriever:
    """
    Recupera chunks de tabelas estáticas e extrai dados estruturados via pandas.

    Fluxo: pool tabular top-K → filtra tabelas estáticas → rerank → extração estruturada
    Retorna (structured_data: str, nodes: list) ou None se sem tabelas relevantes.
    """

    def __init__(self, retriever, reranker, llm):
        self._retriever = retriever
        self._reranker = reranker
        self._llm = llm

    def retrieve(self, question: str) -> tuple[str, list] | None:
        nodes = self._retriever.retrieve(question)

        table_nodes = [n for n in nodes if _is_static_table(n)]
        if not table_nodes:
            return None

        # Sanitiza antes do reranker
        for n in table_nodes:
            n.node.text = _sanitize(n.node.text)

        try:
            reranked = self._reranker.postprocess_nodes(
                table_nodes[:rerank_candidate_limit()],
                query_str=question,
            )
        except Exception:
            log.warning("Reranker falhou em tables — usando fallback", extra={"fallback": True})
            reranked = []

        if not reranked:
            reranked = table_nodes[:_FALLBACK_TOP_N]
        reranked = list(reranked[:structured_top_n()])

        context = limit_context("\n\n---\n\n".join(n.get_content() for n in reranked))
        structured = self._extract_and_calculate(question, context)
        return structured, reranked

    def _extract_and_calculate(self, question: str, context: str) -> str:
        # Fase 1: extração estruturada em JSON (nenhum código do LLM é executado)
        extract_resp = self._llm.complete(
            _EXTRACT_PROMPT.format(context=context, question=question)
        )
        try:
            payload = parse_json_object(extract_resp.text)
            df, data = tabular_payload(payload)
        except StructuredOutputError as exc:
            log.warning("Extracao estruturada de tabela falhou: %s", exc)
            return "[Sem dados estruturados extraídos da tabela]"

        if df is not None:
            data_preview = df.to_string(max_rows=20)
        elif data is not None:
            data_preview = str(data)
        else:
            return "[Sem dados estruturados extraídos da tabela]"

        # Fase 2: cálculo pelo LLM com saída JSON estrita, sem execução de Python
        calc_resp = self._llm.complete(
            _CALCULATE_PROMPT.format(question=question, data_preview=data_preview)
        )
        try:
            return result_text(parse_json_object(calc_resp.text))
        except StructuredOutputError as exc:
            log.warning("Calculo estruturado sobre tabela falhou: %s", exc)
            return data_preview
