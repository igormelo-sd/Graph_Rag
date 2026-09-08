"""
Analysis Engine — agrega resultados dos três retrievers e sintetiza
uma única resposta via LLM.

Fluxo:
    sources selecionados → retrievers em paralelo (asyncio)
    → contexto unificado → LLM (síntese única) → (resposta, source_nodes)
"""
import asyncio
import os

from answer_policy import REFUSAL_TEXT, sanitize_answer
from answer_style import ANALYST_WRITING_GUIDE
from domain_skills import build_domain_prompt_block
from logger import get_logger
from runtime import limit_context, request_timeout_seconds
from provenance import format_source_context, source_labels

log = get_logger(__name__)

_HYDE_PROMPT = """Escreva um parágrafo hipotético, em português, que responderia diretamente à pergunta abaixo como se fosse um trecho de boletim da Fundação Seade. Use tom técnico e inclua números plausíveis apenas como ilustração.

Pergunta: {question}

Parágrafo hipotético:"""

def _deep_search_enabled() -> bool:
    return os.getenv("RAG_DEEP_SEARCH", "0").strip().lower() in {"1", "true", "yes", "on"}

def _hyde_enabled() -> bool:
    return os.getenv("RAG_HYDE", "0").strip().lower() in {"1", "true", "yes", "on"}


def _graph_struct_enabled() -> bool:
    return os.getenv("RAG_GRAPH_STRUCT", "0").strip().lower() in {"1", "true", "yes", "on"}

# ── Prompt de síntese ─────────────────────────────────────────────────────────

_SYNTHESIS_PROMPT = """\
Você é um analista de conjuntura econômica e estatística do Estado de São Paulo.
Sua tarefa é redigir uma análise que responda à pergunta do usuário com base
exclusivamente nas fontes fornecidas abaixo.

FIDELIDADE ÀS FONTES (inegociável)

1. Use somente informações presentes no contexto. Conhecimento externo é proibido.

2. RASTREABILIDADE — Todo fato e todo número da resposta deve ser rastreável a um \
trecho específico do contexto. Organizar, comparar e encadear fatos de trechos \
diferentes em uma mesma narrativa é permitido e esperado; criar fato novo, não: \
nenhuma afirmação causal, estimativa ou conclusão que nenhum trecho sustente, \
direta ou numericamente.

3. SEPARAÇÃO DA EVIDÊNCIA — Use os rótulos de origem apenas internamente para \
verificar o suporte. Não os copie para a resposta. Não escreva citações, nomes \
de arquivos, páginas, abas ou listas de referências, salvo pedido explícito do usuário.
   Se um valor numérico extraído de tabela/série não tiver suporte identificável no \
contexto narrativo adjacente, não o utilize na resposta.

4. DADOS ESTRUTURADOS SEM RÓTULOS — Se a seção de séries temporais ou tabelas contiver \
apenas números sem rótulos claros de indicador e período, ignore essa seção inteiramente \
e baseie a resposta somente no contexto narrativo.

5. CONFLITO DE DADOS — Se um valor numérico na seção estruturada divergir do contexto \
narrativo, prevaleça o contexto narrativo.

6. AUSÊNCIA DE DADOS — Se a informação não está no contexto, responda exatamente:
   '""" + REFUSAL_TEXT + """'

7. EVIDÊNCIA PARCIAL — Responda apenas o que está sustentado. Para cada ponto sem \
suporte suficiente, use somente a mensagem definida no item 6.

8. CÁLCULOS — Se a pergunta pede diferença, variação ou comparação e os dois valores \
estão sustentados no contexto, calcule e mostre a conta \
(ex: 3,4% − 2,8% = 0,6 p.p.).

""" + ANALYST_WRITING_GUIDE + """
{skill_block}
{context_block}

Pergunta: {question}

Resposta:"""

def _build_context_block(
    text_nodes: list,
    tables_data: str | None,
    tables_nodes: list | None,
    ts_data: str | None,
    ts_nodes: list | None = None,
    graph_nodes: list | None = None,
    image_nodes: list | None = None,
) -> str:
    sections = []

    # Consolida texto narrativo: nodes de texto + grafo + nodes de timeseries sem dados estruturados
    narrative_parts = []
    if text_nodes:
        narrative_parts.extend(format_source_context(n) for n in text_nodes)
    if graph_nodes:
        narrative_parts.extend(format_source_context(n) for n in graph_nodes)
    if not ts_data and ts_nodes:
        # Timeseries não produziu dados estruturados — usa conteúdo bruto como narrativa
        narrative_parts.extend(format_source_context(n) for n in ts_nodes)
    if narrative_parts:
        sections.append(
            "[Contexto Narrativo dos Documentos]\n" + "\n\n---\n\n".join(narrative_parts)
        )

    if tables_data:
        labels = source_labels(tables_nodes or [])
        sections.append(f"[Dados Estruturados de Tabelas]\n{labels}\n{tables_data}")

    if ts_data:
        labels = source_labels(ts_nodes or [])
        sections.append(f"[Dados de Séries Temporais]\n{labels}\n{ts_data}")

    if image_nodes:
        labels = source_labels(image_nodes)
        img_parts = [format_source_context(n) for n in image_nodes]
        sections.append(f"[Descrições de Gráficos e Figuras (Visão Local)]\n{labels}\n" + "\n\n---\n\n".join(img_parts))

    return "\n\n" + "\n\n".join(sections) if sections else ""


# ── Engine ────────────────────────────────────────────────────────────────────

class AnalysisEngine:
    """
    Orquestra os retrievers em paralelo e sintetiza a resposta final com um
    único LLM call, combinando contexto narrativo + dados estruturados.
    """

    def __init__(
        self,
        text_retriever,
        tables_retriever,
        timeseries_retriever,
        llm,
        domain_skills=None,
        labor_market_skill=None,
        graph_retriever=None,
        images_retriever=None,
    ):
        self._text = text_retriever
        self._tables = tables_retriever
        self._ts = timeseries_retriever
        self._images = images_retriever
        self._llm = llm
        self._domain_skills = domain_skills
        self._labor_skill = labor_market_skill
        self._graph = graph_retriever
        self._last_chart_payload: dict | None = None

    async def answer(
        self,
        question: str,
        sources: list[str],
        rewritten_query: str,
        is_labor_market: bool = False,
        rewritten_queries: list[str] | None = None,
    ) -> tuple[str, list]:
        """
        Executa os retrievers necessários em paralelo e retorna
        (resposta_texto, all_source_nodes).
        Suporta deep search com múltiplas rewritten_queries e HyDE opcional.
        """
        # Deep search: usa lista de queries alternativas se habilitado
        queries = [rewritten_query]
        if _deep_search_enabled() and rewritten_queries:
            # filtra válidas e limita a 3
            alt = [str(q).strip() for q in rewritten_queries if isinstance(q, str) and str(q).strip()]
            # dedup preservando ordem
            seen = set()
            uniq = []
            for q in [rewritten_query] + alt:
                if q not in seen:
                    seen.add(q)
                    uniq.append(q)
            queries = uniq[:3]
            if len(queries) > 1:
                log.info("Deep search: %d queries alternativas", len(queries), extra={"queries": queries[:3]})

        # HyDE opcional: gera doc hipotético para reforçar embedding denso
        hyde_query: str | None = None
        if _hyde_enabled() and self._llm is not None:
            try:
                hyde_resp = await asyncio.to_thread(self._llm.complete, _HYDE_PROMPT.format(question=question))
                hyde_query = (hyde_resp.text or "").strip()[:800]
                if hyde_query:
                    log.info("HyDE doc gerado (%d chars)", len(hyde_query))
            except Exception as exc:
                log.warning("HyDE falhou: %s", exc)

        # Monta corrotinas apenas para as fontes selecionadas
        # Se múltiplas queries, expande cada fonte × query
        keys: list[str] = []
        coros = []
        for q in queries:
            suffix = "" if len(queries) == 1 else f"@{queries.index(q)}"
            if "text" in sources:
                keys.append(f"text{suffix}")
                coros.append(asyncio.to_thread(self._text.retrieve, q))
            if "tables" in sources:
                keys.append(f"tables{suffix}")
                coros.append(asyncio.to_thread(self._tables.retrieve, q))
            if "timeseries" in sources:
                keys.append(f"ts{suffix}")
                coros.append(asyncio.to_thread(self._ts.retrieve, q))
            if "image" in sources and self._images is not None:
                keys.append(f"image{suffix}")
                coros.append(asyncio.to_thread(self._images.retrieve, q))
        # HyDE retrieval extra (text apenas, para não poluir séries)
        if hyde_query and "text" in sources:
            keys.append("text_hyde")
            coros.append(asyncio.to_thread(self._text.retrieve, hyde_query))

        results = await asyncio.wait_for(
            asyncio.gather(*coros, return_exceptions=True),
            timeout=request_timeout_seconds(),
        )
        result_map = {}
        for key, result in zip(keys, results):
            if isinstance(result, BaseException):
                log.warning("Retriever %s falhou; continuando com fontes parciais: %s", key, result)
            else:
                result_map[key] = result

        # Coleta resultados — agrega múltiplas queries (deep search) com dedup por node_id
        def _dedup_nodes(nodes: list) -> list:
            seen = set()
            out = []
            for n in nodes:
                nid = getattr(getattr(n, "node", n), "node_id", None) or getattr(n, "id", None) or id(n)
                if nid not in seen:
                    seen.add(nid)
                    out.append(n)
            return out

        text_nodes: list = []
        for k, v in result_map.items():
            if k.startswith("text"):
                if isinstance(v, list):
                    text_nodes.extend(v)
        text_nodes = _dedup_nodes(text_nodes)
        # Costura: traz NEXT_CHUNK/SAME_PAGE vizinhos quando contexto foi partido entre chunks
        if _graph_struct_enabled() and self._graph is not None and text_nodes:
            try:
                neighbors = self._graph.retrieve_neighbors(text_nodes)
                if neighbors:
                    combined = _dedup_nodes(text_nodes + neighbors)
                    # limita vizinhos a orçamento: não duplica mais que 30% do top_n
                    text_nodes = combined[: len(text_nodes) + min(len(neighbors), 6)]
                    log.info("Costura grafo: +%d vizinhos NEXT_CHUNK/SAME_PAGE", len(neighbors))
            except Exception as exc:
                log.warning("Costura grafo falhou: %s", exc)

        tables_data: str | None = None
        tables_nodes: list = []
        for k, v in result_map.items():
            if k.startswith("tables") and v is not None:
                td, tn = v
                if td:
                    tables_data = (tables_data + "\n\n" + td) if tables_data else td
                if tn:
                    tables_nodes.extend(tn)
        tables_nodes = _dedup_nodes(tables_nodes)

        ts_data: str | None = None
        ts_nodes: list = []
        for k, v in result_map.items():
            if k.startswith("ts") and v is not None:
                if isinstance(v, tuple) and len(v) == 2:
                    td, tn = v
                    if td:
                        ts_data = td  # usa último estruturado válido
                    if isinstance(tn, list):
                        ts_nodes.extend(tn)
                elif isinstance(v, list):
                    ts_nodes.extend(v)
        ts_nodes = _dedup_nodes(ts_nodes)
        # guarda payload para gráfico (API)
        self._last_chart_payload = getattr(self._ts, "_last_chart_payload", None)

        image_nodes: list = []
        for k, v in result_map.items():
            if k.startswith("image"):
                if isinstance(v, list):
                    image_nodes.extend(v)
        image_nodes = _dedup_nodes(image_nodes)

        # Grafo: executa separadamente (precisa dos IDs dos nós já coletados para deduplicar)
        graph_nodes: list = []
        if "graph" in sources and self._graph is not None:
            existing_ids = {
                getattr(n.node if hasattr(n, "node") else n, "node_id", None)
                for n in text_nodes + tables_nodes + ts_nodes + image_nodes
            }
            try:
                graph_nodes = await asyncio.wait_for(
                    asyncio.to_thread(self._graph.retrieve, rewritten_query, existing_ids),
                    timeout=min(60.0, request_timeout_seconds()),
                )
            except Exception as exc:
                log.warning("GraphRetriever falhou; continuando sem grafo: %s", exc)

        all_source_nodes = text_nodes + tables_nodes + ts_nodes + image_nodes + graph_nodes

        # Síntese: único LLM call com contexto unificado
        context_block = limit_context(
            _build_context_block(
                text_nodes, tables_data, tables_nodes, ts_data, ts_nodes, graph_nodes, image_nodes
            )
        )

        if not context_block.strip():
            return REFUSAL_TEXT, []

        skill_block = build_domain_prompt_block(
            self._domain_skills,
            question,
            is_labor_market=is_labor_market,
            legacy_labor_skill=self._labor_skill,
        )

        response = self._llm.complete(
            _SYNTHESIS_PROMPT.format(
                skill_block=skill_block,
                context_block=context_block,
                question=question,
            )
        )

        return sanitize_answer(response.text, question=question), all_source_nodes
