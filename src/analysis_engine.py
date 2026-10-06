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
from query_results import AnswerResult, SeriesResult
from domain_ontology import prompt_block
from rag_selection import fuse, pack_context, sufficiency

log = get_logger(__name__)

_HYDE_PROMPT = """Escreva uma descrição conceitual curta para busca em boletins econômicos. Preserve exatamente indicador, território e período da pergunta. Não invente valores, percentuais, fatos, tendências ou causas. Não responda à pergunta; descreva apenas o conteúdo documental necessário.

Pergunta: {question}

Parágrafo hipotético:"""

def _deep_search_enabled() -> bool:
    return os.getenv("RAG_DEEP_SEARCH", "0").strip().lower() in {"1", "true", "yes", "on"}

def _hyde_enabled() -> bool:
    return os.getenv("RAG_HYDE", "0").strip().lower() in {"1", "true", "yes", "on"}


def _graph_struct_enabled() -> bool:
    return os.getenv("RAG_GRAPH_STRUCT", "1").strip().lower() in {"1", "true", "yes", "on"}

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
   Valores de tabela/série precisam de células e rótulos documentais identificáveis \
(indicador, período, território e unidade), incluindo título/notas quando necessários. \
Não trate metadados inferidos pelo LLM como evidência documental.

4. DADOS ESTRUTURADOS SEM RÓTULOS — Se a seção de séries temporais ou tabelas contiver \
apenas números sem rótulos claros de indicador e período, ignore essa seção inteiramente \
e baseie a resposta somente no contexto narrativo.

5. CONFLITO DE DADOS — Se a extração estruturada divergir da fonte original, descarte \
o valor extraído incorretamente. Se duas fontes originais apresentarem valores \
divergentes para os mesmos recortes, sinalize a divergência; não escolha um valor \
por preferência entre narrativa e tabela, nem presuma revisão ou metodologia.

6. AUSÊNCIA DE DADOS — Se a informação não está no contexto, responda exatamente:
   '""" + REFUSAL_TEXT + """'

7. EVIDÊNCIA PARCIAL — Responda apenas o que está sustentado. Para cada ponto sem \
suporte suficiente, use somente a mensagem definida no item 6.

8. CÁLCULOS — Reproduza apenas operações da seção Cálculo Python, com a fórmula.
Não faça contas novas. Se não houver cálculo disponível, apresente os valores
originais e informe que o cálculo solicitado não foi validado. A aritmética
correta não garante que os operandos selecionados respondam à pergunta.

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
        knowledge_nodes=None,
        final_reranker=None,
    ):
        self._text = text_retriever
        self._tables = tables_retriever
        self._ts = timeseries_retriever
        self._images = images_retriever
        self._llm = llm
        self._final_reranker = final_reranker
        self._domain_skills = domain_skills
        self._labor_skill = labor_market_skill
        self._graph = graph_retriever
        from knowledge_analytics import CorpusKnowledge
        self._knowledge = CorpusKnowledge(list(knowledge_nodes or []))
        # Snapshot documental para expansão local, independente de grafo ou memória.
        from collections import defaultdict
        self._narrative_windows = defaultdict(list)
        for node in knowledge_nodes or []:
            md = getattr(node, "metadata", {}) or {}
            if md.get("type") == "text" and not md.get("raptor_level"):
                self._narrative_windows[(str(md.get("source_file", "")), str(md.get("page", "")))].append(node)

    def knowledge_report(self, question=""):
        return self._knowledge.report(question)

    def clarification(self, question):
        from knowledge_analytics import clarification_request
        return clarification_request(question, self._knowledge.available_regions)

    async def answer(
        self,
        question: str,
        sources: list[str],
        rewritten_query: str,
        is_labor_market: bool = False,
        rewritten_queries: list[str] | None = None,
    ) -> AnswerResult:
        """
        Executa os retrievers em paralelo e retorna texto, fontes e gráfico
        em um AnswerResult isolado por chamada (desempacotável em texto/fontes).
        Suporta deep search com múltiplas rewritten_queries e HyDE opcional.
        """
        clarification = self.clarification(question)
        if clarification:
            return AnswerResult(clarification["question"], [], clarification=clarification)
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
                from domain_ontology import preserve_query
                hyde_query = preserve_query(question, (hyde_resp.text or "").strip()[:800])
                if hyde_query:
                    log.info("HyDE doc gerado (%d chars)", len(hyde_query))
            except Exception as exc:
                log.warning("HyDE falhou: %s", exc)

        # Monta corrotinas apenas para as fontes selecionadas
        # Se múltiplas queries, expande cada fonte × query
        keys: list[str] = []
        coros = []
        for qi, q in enumerate(queries):
            suffix = "" if len(queries) == 1 else f"@{qi}"
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
        tables_data: str | None = None
        calculations = []
        tables_nodes: list = []
        for k, v in result_map.items():
            if k.startswith("tables") and v is not None:
                calculations.extend(getattr(v, "calculations", []))
                td, tn = v
                if td:
                    tables_data = (tables_data + "\n\n" + td) if tables_data else td
                if tn:
                    tables_nodes.extend(tn)
        tables_nodes = _dedup_nodes(tables_nodes)

        ts_data: str | None = None
        timeseries_chart = None
        ts_nodes: list = []
        for k, v in result_map.items():
            if k.startswith("ts") and v is not None:
                calculations.extend(getattr(v, "calculations", []))
                if isinstance(v, SeriesResult):
                    if v.data:
                        ts_data = v.data
                        timeseries_chart = v.chart
                    ts_nodes.extend(v.nodes)
                elif isinstance(v, tuple) and len(v) == 2:
                    td, tn = v
                    if td:
                        ts_data = td  # usa último estruturado válido
                    if isinstance(tn, list):
                        ts_nodes.extend(tn)
                elif isinstance(v, list):
                    ts_nodes.extend(v)
        ts_nodes = _dedup_nodes(ts_nodes)

        image_nodes: list = []
        for k, v in result_map.items():
            if k.startswith("image"):
                if isinstance(v, list):
                    image_nodes.extend(v)
        image_nodes = _dedup_nodes(image_nodes)

        # Grafo: executa separadamente (precisa dos IDs dos nós já coletados para deduplicar)
        graph_nodes: list = []
        retrieval_paths = []

        def record_paths(nodes):
            import json
            for node in nodes:
                inner = getattr(node, "node", node)
                raw = (getattr(inner, "metadata", {}) or {}).get("graph_paths")
                if raw:
                    try:
                        decoded = json.loads(raw)
                        if isinstance(decoded, list):
                            retrieval_paths.append({"node_id": str(inner.node_id), "paths": decoded})
                    except (TypeError, ValueError):
                        log.warning("Caminho de recuperação com formato inválido")

        if "graph" in sources and self._graph is not None:
            existing_ids = {
                getattr(n.node if hasattr(n, "node") else n, "node_id", None)
                for n in text_nodes + tables_nodes + ts_nodes + image_nodes
            }
            try:
                graph_nodes = await asyncio.wait_for(
                    asyncio.to_thread(self._graph.retrieve, rewritten_query),
                    timeout=min(60.0, request_timeout_seconds()),
                )
                record_paths(graph_nodes)
                graph_nodes = [node for node in graph_nodes if getattr(getattr(node, "node", node), "node_id", None) not in existing_ids]
            except Exception as exc:
                log.warning("GraphRetriever falhou; continuando sem grafo: %s", exc)

        all_source_nodes = text_nodes + tables_nodes + ts_nodes + image_nodes + graph_nodes
        # Tabelas, séries e imagens também recebem título/notas por travessia de arestas.
        if _graph_struct_enabled() and self._graph is not None and all_source_nodes:
            try:
                context_nodes = await asyncio.to_thread(self._graph.retrieve_context, all_source_nodes, 6)
                record_paths(context_nodes)
                graph_nodes = _dedup_nodes(graph_nodes + context_nodes)
                all_source_nodes = _dedup_nodes(text_nodes + tables_nodes + ts_nodes + image_nodes + graph_nodes)
            except Exception as exc:
                log.warning("Contexto documental do grafo indisponível: %s", exc)
        knowledge = await asyncio.to_thread(self.knowledge_report, question)

        # Segunda busca limitada, dirigida somente às lacunas de cobertura candidata.
        coverage_report = sufficiency(question, all_source_nodes)
        repair_nodes = []
        if coverage_report["missing"] and "text" in sources:
            wanted = coverage_report["missing"]
            repair_query = question + "\nRecortes ainda necessários: " + "; ".join(
                value for values in wanted.values() for value in values)
            try:
                extra = await asyncio.wait_for(asyncio.to_thread(self._text.retrieve, repair_query),
                                               timeout=min(30.0, request_timeout_seconds()))
                text_nodes = _dedup_nodes(text_nodes + extra)
                all_source_nodes = _dedup_nodes(all_source_nodes + extra)
                repair_nodes = extra
            except Exception as exc:
                log.warning("Busca complementar indisponível: %s", exc)

        retrieval_lists = []
        for result in result_map.values():
            if isinstance(result, SeriesResult):
                retrieval_lists.append(result.nodes)
            elif isinstance(result, list):
                retrieval_lists.append(result)
            elif isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], list):
                retrieval_lists.append(result[1])
        ranked = await asyncio.to_thread(fuse, retrieval_lists + [repair_nodes, graph_nodes],
                                        question, self._final_reranker)
        # Expansão limitada de vizinhos narrativos com mesma página/seção.
        from llama_index.core.schema import NodeWithScore
        from rag_selection import node_key
        neighbor_map = {}
        for node in ranked[:6]:
            md = getattr(node, "metadata", {}) or {}
            if md.get("type") != "text":
                continue
            try:
                position = int(md.get("chunk_id", 0))
            except (ValueError, TypeError):
                continue
            neighbors = []
            for candidate in self._narrative_windows.get((str(md.get("source_file", "")), str(md.get("page", ""))), []):
                cm = candidate.metadata
                try:
                    adjacent = abs(int(cm.get("chunk_id", 0)) - position) == 1
                except (ValueError, TypeError):
                    adjacent = False
                if adjacent and cm.get("section") == md.get("section"):
                    neighbors.append(NodeWithScore(node=candidate))
            neighbor_map[node_key(node)] = neighbors[:2]
        bundles = []
        for key, result in result_map.items():
            if isinstance(result, SeriesResult) and result.data:
                bundles.append((result.data, result.nodes))
        context_block, all_source_nodes = pack_context(ranked, question, bundles, neighbor_map)
        # Apenas cálculos cujas fontes chegaram integralmente ao contexto.
        from rag_selection import node_key
        included_ids = {node_key(n) for n in all_source_nodes}
        calculations = [c for c in calculations if c.get("formula") and c["formula"] in context_block and all(
            source.get("node_id") in included_ids
            for operand in c.get("operands", []) for source in operand.get("sources", []))]
        coverage_report = sufficiency(question, all_source_nodes)
        knowledge["retrieval_coverage"] = coverage_report
        retrieval_paths = [path for path in retrieval_paths if path.get("node_id") in included_ids]
        if timeseries_chart and not any(key.startswith("ts") and isinstance(result, SeriesResult)
                and result.chart == timeseries_chart and all(node_key(n) in included_ids for n in result.nodes)
                for key, result in result_map.items()):
            timeseries_chart = None

        # Síntese: único LLM call com contexto unificado

        if not context_block.strip():
            knowledge["retrieval_coverage"]["status"] = "no_context_fits" if ranked else "no_evidence"
            return AnswerResult(REFUSAL_TEXT, [], knowledge=knowledge)

        skill_block = build_domain_prompt_block(
            self._domain_skills,
            question,
            is_labor_market=is_labor_market,
            legacy_labor_skill=self._labor_skill,
        )
        skill_block += prompt_block(question)
        if coverage_report["missing"]:
            import json
            skill_block += "\n[Cobertura candidata incompleta] " + json.dumps(coverage_report["missing"], ensure_ascii=False)
            skill_block += "\nConfira as fontes literais. Responda somente partes sustentadas; não preencha lacunas nem compare recortes incompatíveis. Esta checagem não prova ausência no corpus."
        if knowledge["divergences"]:
            import json
            conflicts = [{"dimensions": item["dimensions"], "values": [a["normalized_value"] for a in item["alternatives"]]}
                         for item in knowledge["divergences"][:10]]
            skill_block += "\n[Auditoria de candidatos, não fatos] Há valores divergentes no índice: " + json.dumps(conflicts, ensure_ascii=False)
            skill_block += "\nSinalize a divergência se aparecer nas fontes recuperadas; não escolha um valor nem infira revisão/metodologia sem evidência. Não converta hipótese ou associação em causalidade."

        response = await asyncio.to_thread(
            self._llm.complete,
            _SYNTHESIS_PROMPT.format(
                skill_block=skill_block,
                context_block=context_block,
                question=question,
            )
        )

        return AnswerResult(sanitize_answer(response.text, question=question), all_source_nodes, timeseries_chart, calculations,
                            knowledge=knowledge, retrieval_paths=retrieval_paths)
