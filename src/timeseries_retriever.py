"""
TimeSeries Retriever — recupera chunks de séries temporais (mensal/trimestral)
e os estrutura via pandas para o Analysis Engine.

"Temporal" = tabelas com granularidade sequencial ao longo do tempo, adequadas para
análise de tendências, crescimento e evolução de indicadores econômicos.
"""
import re
import pandas as pd

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


# Marcadores temporais reconhecíveis em português — sinal positivo de série válida
_PERIOD_PATTERN = re.compile(
    r"([1-4][oO°]\s*trim)"               # 1o trim, 2º trim …
    r"|(\b(19|20)\d{2}\b)"               # anos: 1990–2099
    r"|(jan(eiro)?|fev(ereiro)?|mar(ço)?|abr(il)?"
    r"|mai(o)?|jun(ho)?|jul(ho)?|ago(sto)?"
    r"|set(embro)?|out(ubro)?|nov(embro)?|dez(embro)?)"
    r"|(\b(período|data|mês|mes|trimestre|semestre|anual|mensal)\b)",
    re.IGNORECASE,
)


def _context_has_temporal_labels(context: str) -> bool:
    """
    Verifica (por sinal positivo) se o contexto contém rótulos temporais reconhecíveis.
    Retorna False para contextos com apenas números e índices inteiros — indica
    serialização incorreta de tabela (ex: '0: 17,5\\n1: 16,5\\n...').
    """
    return bool(_PERIOD_PATTERN.search(context))


def _df_is_valid_timeseries(df) -> bool:
    """
    Verifica se o DataFrame extraído tem estrutura de série temporal útil:
      - Pelo menos 2 linhas e 2 colunas.
      - Primeira coluna com rótulos textuais (não puramente numérica) — indica períodos.
    """
    if df is None or df.shape[0] < 2 or df.shape[1] < 2:
        return False
    first_col = df.iloc[:, 0]
    # Anos vindos de CSV/XLSX frequentemente chegam como inteiros.
    if pd.api.types.is_numeric_dtype(first_col):
        numeric = pd.to_numeric(first_col, errors="coerce")
        if numeric.isna().any():
            return False
        years = numeric.astype(float)
        return bool(years.between(1900, 2100).all())
    return True


# Granularidades que indicam série temporal → incluídas neste retriever
_TEMPORAL_KEYWORDS = {
    "mensal", "trimestral", "semestral", "bimestral",
    "semanal", "diário", "diaria", "diária", "anual", "ano a ano",
}

# ── Prompts ───────────────────────────────────────────────────────────────────

_EXTRACT_PROMPT = """\
Você é um extrator de séries temporais. Leia os trechos abaixo e extraia os dados \
em formato de série temporal para responder à pergunta.

Retorne SOMENTE um objeto JSON válido, sem markdown ou texto adicional.
Para uma série tabular, use:
{{"columns": ["Período", "Valor"], "rows": [["2023", 1.2], ["2024", 1.4]]}}
Para uma série simples, use:
{{"data": {{"2023": 1.2, "2024": 1.4}}}}
Regras:
- Use apenas strings, números, booleanos ou null nas células.
- Ordene os dados cronologicamente quando possível.
- Use nomes de colunas em português (ex: "Período", "Valor", "Variação").
- Não inclua código, comentários ou campos adicionais.

Trechos:
{context}

Pergunta: {question}
"""

_RETRY_EXTRACT_PROMPT = """\
Sua resposta anterior falhou porque o campo 'data' estava vazio.
Retorne SOMENTE JSON válido usando EXCLUSIVAMENTE o formato colunar — não use 'data':
{{"columns": ["Período", "Valor"], "rows": [["2023", 1.2], ["2024", 1.4]]}}
Regras: strings/números/booleanos/null apenas, ordenado cronologicamente, colunas em português.

Trechos:
{context}

Pergunta: {question}
"""

_ANALYZE_PROMPT = """\
Você tem uma série temporal estruturada abaixo. Analise-a usando exclusivamente esses dados.
Retorne SOMENTE JSON válido no formato {{"resultado": "texto final"}}.
Regras:
- Não inclua código ou explicações fora do campo `resultado`.
- Calcule variações, tendências e estatísticas relevantes para a pergunta.
- Formate números com separador de milhar e 2 casas decimais.

Pergunta: {question}

Série temporal disponível:
{data_preview}
"""

# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_temporal_table(node) -> bool:
    """True se o node for tabela com granularidade temporal."""
    if node.metadata.get("type") != "table":
        return False
    gran = str(node.metadata.get("table_granularidade") or "").lower()
    return any(kw in gran for kw in _TEMPORAL_KEYWORDS)


# ── Retriever ─────────────────────────────────────────────────────────────────

class TimeSeriesRetriever:
    """
    Recupera chunks de séries temporais e extrai dados estruturados via pandas.

    Fluxo: pool tabular top-K → filtra séries temporais → rerank → extração + análise
    Retorna (structured_data: str, nodes: list) ou None se sem dados temporais relevantes.
    """

    def __init__(self, retriever, reranker, llm):
        self._retriever = retriever
        self._reranker = reranker
        self._llm = llm
        self._last_chart_payload: dict | None = None

    def retrieve(self, question: str) -> tuple[str, list] | None:
        nodes = self._retriever.retrieve(question)

        ts_nodes = [n for n in nodes if _is_temporal_table(n)]
        if not ts_nodes:
            return None

        # Sanitiza antes do reranker
        for n in ts_nodes:
            n.node.text = _sanitize(n.node.text)

        try:
            reranked = self._reranker.postprocess_nodes(
                ts_nodes[:rerank_candidate_limit()],
                query_str=question,
            )
        except Exception:
            log.warning("Reranker falhou em timeseries — usando fallback", extra={"fallback": True})
            reranked = []

        if not reranked:
            reranked = ts_nodes[:_FALLBACK_TOP_N]
        reranked = list(reranked[:structured_top_n()])

        context = limit_context("\n\n---\n\n".join(n.get_content() for n in reranked))

        # Pré-filtro: contexto sem rótulo temporal → não vale chamar o LLM de extração
        if not _context_has_temporal_labels(context):
            log.warning(
                "Contexto sem rotulos temporais reconheciveis — revertendo para narrativa",
                extra={"event": "ts_no_period_labels"},
            )
            return None, reranked

        structured_result = self._extract_and_analyze(question, context)
        # _extract_and_analyze agora retorna (texto, payload)
        if isinstance(structured_result, tuple):
            structured, chart_payload = structured_result
        else:
            structured, chart_payload = structured_result, None
        # guarda payload para o engine montar o chart (acessível via retriever._last_chart_payload)
        self._last_chart_payload = chart_payload
        if structured is None:
            # DataFrame inválido na extração — narrativa como fallback
            log.warning(
                "Extracao retornou estrutura invalida — revertendo para narrativa",
                extra={"event": "ts_extraction_fallback"},
            )
            return None, reranked
        return structured, reranked

    def _extract_and_analyze(self, question: str, context: str) -> tuple[str, dict | None]:
        # Fase 1: extração estruturada em JSON (nenhum código do LLM é executado)
        # Retorna (texto_analisado, payload_para_grafico)
        payload_for_chart: dict | None = None

        def _try_extract(prompt: str) -> tuple:
            resp = self._llm.complete(prompt)
            payload = parse_json_object(resp.text)
            df, data = tabular_payload(payload)
            # guarda payload original para o gráfico
            # payload pode ser {columns, rows} ou {data: {...}}
            p = dict(payload)
            # normaliza para chart: se for data dict, mantém; se for columns/rows, mantém
            return df, data, p

        try:
            df, data, payload_for_chart = _try_extract(_EXTRACT_PROMPT.format(context=context, question=question))
        except StructuredOutputError as exc:
            # Reparo: LLM devolveu {"data": {}} vazio — tenta colunar
            msg = str(exc)
            if "O campo 'data' deve ser um objeto não vazio" in msg:
                log.warning("Extracao data vazio — tentando fallback colunar", extra={"event": "ts_retry_columns"})
                try:
                    df, data, payload_for_chart = _try_extract(_RETRY_EXTRACT_PROMPT.format(context=context, question=question))
                except StructuredOutputError as exc2:
                    log.warning("Extracao estruturada de serie temporal falhou (retry): %s", exc2)
                    return None, None
            else:
                log.warning("Extracao estruturada de serie temporal falhou: %s", exc)
                return None, None

        if df is not None:
            if not _df_is_valid_timeseries(df):
                log.warning(
                    "DataFrame extraido sem estrutura de serie temporal valida "
                    "(colunas: %s, shape: %s) — abortando analise",
                    list(df.columns), df.shape,
                    extra={"event": "ts_invalid_df"},
                )
                return None, None  # retrieve() usará fallback narrativo
            data_preview = df.to_string(max_rows=40)
            # para gráfico, usa payload colunar original
        elif data is not None:
            data_preview = str(data)
            # payload_for_chart já contém {"data": {...}}
        else:
            return "[Sem dados de série temporal extraídos]", None

        # Fase 2: análise pelo LLM com saída JSON estrita, sem execução de Python
        analyze_resp = self._llm.complete(
            _ANALYZE_PROMPT.format(question=question, data_preview=data_preview)
        )
        try:
            return result_text(parse_json_object(analyze_resp.text)), payload_for_chart
        except StructuredOutputError as exc:
            log.warning("Analise estruturada de serie temporal falhou: %s", exc)
            return data_preview, payload_for_chart
