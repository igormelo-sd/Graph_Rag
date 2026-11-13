"""Estratégias de recuperação comparadas sobre o mesmo ranking inicial.

As duas variantes recebem os mesmos nós, os mesmos trechos iniciais e a mesma
reserva (os trechos seguintes do ranking); só muda o que acontece depois: o RAG
simples usa a reserva, o GraphRAG usa candidatos do grafo. Os imports do GraphRAG são tardios porque dependem de
``graph_modules()`` e não podem ocorrer no ``--help``.
"""
from dataclasses import dataclass, field
from types import SimpleNamespace

GLOBAL_TASK = "Consolide evidências relevantes à pergunta, preservando fontes. Pergunta: "


@dataclass
class Retrieval:
    results: list[dict]
    diagnostics: dict = field(default_factory=dict)


def as_result(item) -> dict:
    return {"text": item.node.text, "source": item.metadata.get("source_file", "?"),
            "page": item.metadata.get("page"), "number": item.metadata.get("chunk_id"),
            "score": item.score, "metadata": dict(item.metadata)}


def build_table_proxy(nodes):
    """Uma linha de cada tabela do índice, usada como semente de apoio das linhas exatas do corpus inteiro."""
    proxy = {}
    for node in nodes:
        if node.metadata.get("type") == "table":
            proxy.setdefault((str(node.metadata.get("source_file")), str(node.metadata.get("page"))), node)
    return proxy


def proxy_seeds(table_proxy, ranked):
    """Trechos iniciais mais, para cada linha exata fora do índice, uma linha da mesma tabela como semente.

    Essas linhas não existem no grafo nem nos escopos lexicais; a tabela delas existe. Os apoios não entram
    no contexto, só guiam a expansão.
    """
    from llama_index.core.schema import NodeWithScore
    present = {item.node_id for item in ranked}
    proxies = []
    for item in ranked:
        if str(item.metadata.get("retrieval_method", "")).startswith("structured"):
            key = (str(item.metadata.get("source_file")), str(item.metadata.get("sheet") or "Planilha"))
            proxy = table_proxy.get(key)
            if proxy is not None and proxy.node_id not in present:
                present.add(proxy.node_id)
                proxies.append(NodeWithScore(node=proxy, score=0.0))
    return list(ranked) + proxies


def fill_with_reserve(extras, reserve, slots):
    """Completa as vagas extras com os próximos trechos do ranking comum, depois dos candidatos aceitos.

    O grafo (ou a expansão lexical) soma-se ao ranking em vez de substituir a faixa além dos `top_k`
    primeiros, e o total de extras nunca passa de `slots`: o orçamento de contexto é o do RAG simples.
    """
    taken = {item.node_id for item in extras}
    return [item for item in reserve if item.node_id not in taken][:max(0, slots - len(extras))]


class SimpleVariant:
    """Sem grafo: mesmos pais literais e mesmo número de vagas que o GraphRAG.

    Em vez de candidatos do grafo, ocupa as vagas extras com os próximos trechos
    do ranking inicial comum (`baseline_extra_slots`). Nenhum módulo de grafo é usado.
    """

    graph_extraction = "disabled"

    def __init__(self, nodes, client, settings, artifacts):
        self.slots = settings.get("baseline_extra_slots", 0)

    def retrieve(self, question, ranked, reserve=()) -> Retrieval:
        from parent_context import expand_parents
        extras = list(reserve)[:self.slots]
        diagnostics = {"extras_from_reserve": [item.node_id for item in extras]}
        return Retrieval([as_result(item) for item in expand_parents(list(ranked) + extras)], diagnostics)


class GraphVariant:
    """Com grafo: candidatos do grafo escolhidos pelo reranker, pais e, em perguntas globais, comunidades.

    O grafo propõe candidatos a partir dos trechos iniciais (trechos da mesma tabela ou
    documento com rótulos raros da pergunta, título, notas, dicionários e continuidade do
    texto) e da própria pergunta (observações por recorte e lacunas); o reranker decide
    quais entram (comparacao/graph_selection.py). Os candidatos aceitos vêm antes dos
    próximos trechos do ranking comum, que completam as vagas extras até o mesmo total
    do RAG simples (`baseline_extra_slots`). O ranking inicial não muda.
    """

    graph_extraction = "registered_entities_only"
    uses_reranker = True

    def __init__(self, nodes, client, settings, artifacts, reranker=None):
        # Construído antes da cronometragem, como o carregamento dos modelos.
        from llama_index.core.graph_stores import SimplePropertyGraphStore
        from graph_indexing import inject_deterministic_triplets
        from graph_retriever import GraphRetriever
        self.nodes, self.client, self.settings, self.reranker = nodes, client, settings, reranker
        self.summaries_path = artifacts / "community_summaries.json"
        self.store = SimplePropertyGraphStore()
        inject_deterministic_triplets(self.store, nodes, structural=True)
        self.graph = GraphRetriever(SimpleNamespace(property_graph_store=self.store), None, use_llm=False)
        self.table_proxy = build_table_proxy(nodes)

    def retrieve(self, question, ranked, reserve=()) -> Retrieval:
        from community_search import is_global_question
        if is_global_question(question):
            return self._global(question)
        from parent_context import expand_parents
        extras, diagnostics = self._expand(question, ranked)
        filler = fill_with_reserve(extras, reserve, self.settings.get("baseline_extra_slots", 0))
        return Retrieval([as_result(item) for item in expand_parents(list(ranked) + extras + filler)],
                         {"graph": diagnostics, "extras_from_reserve": [item.node_id for item in filler]})

    def candidates(self, question, ranked):
        """Candidatos do grafo sem repetição nem sementes, marcados com a origem.

        O pool de entidades raras ficou de fora: na rodada v4_dev_20261112_r1 propôs 122
        candidatos e o reranker aceitou 2, ao custo de pontuar todos eles.
        """
        from comparacao.graph_selection import POOL
        seeds = self.seeds(ranked)
        seen = {item.node_id for item in seeds}
        pools = [("label", self.graph.label_candidates(seeds, question, POOL)),
                 ("documentary", self.graph.retrieve_context(seeds, self.settings["graph_context_limit"])),
                 ("query", self.graph.retrieve(question, exclude_ids=seen)[:POOL])]
        if self.settings.get("graph_ppr"):
            pools.append(("ppr", self.graph.retrieve_ppr(seeds, question, POOL)))
        if self.settings.get("gap_planning"):
            # Recortes da pergunta (indicador, território, período, setor) que o contexto inicial não sustenta.
            from rag_selection import sufficiency
            missing = sufficiency(question, list(ranked))["missing"]
            if missing:
                pools.append(("gap", self.graph.retrieve_gaps(question, missing, exclude_ids=seen)))
        found = []
        for origin, items in pools:
            for item in items:
                if item.node_id not in seen:
                    seen.add(item.node_id)
                    item.node.metadata["graph_origin"] = origin
                    found.append(item)
        return found

    def seeds(self, ranked):
        return proxy_seeds(self.table_proxy, ranked)

    def _expand(self, question, ranked):
        """Extras aceitos pelo reranker, depois do ranking inicial e sem reordená-lo."""
        from comparacao.graph_selection import accept_extras
        return accept_extras(question, list(ranked), self.candidates(question, ranked), self.reranker,
                             self.settings["max_per_table"])

    def _global(self, question) -> Retrieval:
        from community_search import CommunitySearch
        search = CommunitySearch(self.store, self.nodes, self.client, self.summaries_path)
        summary, records = search.consolidate(GLOBAL_TASK + question)
        result = {"text": summary, "source": "resumos de comunidades (derivados)", "page": None,
                  "number": 1, "score": 0.0, "metadata": {"source_ids": sorted(search.nodes)}}
        return Retrieval([result], {"all_communities_processed": True, "communities": len(records)})


class LexicalVariant:
    """Controle do GraphRAG: a expansão lexical por tabela e documento, sem grafo.

    Mesmos trechos iniciais, mesma seleção pelo reranker e mesmos pais; só o gerador de candidatos
    muda: termos raros da pergunta nas linhas da mesma tabela e nos trechos do mesmo documento,
    a partir dos metadados dos trechos (comparacao/lexical.py).
    """

    graph_extraction = "disabled"
    uses_reranker = True

    def __init__(self, nodes, client, settings, artifacts, reranker=None):
        from comparacao.lexical import LexicalExpander
        self.settings, self.reranker = settings, reranker
        self.expander = LexicalExpander(nodes)
        self.table_proxy = build_table_proxy(nodes)

    def retrieve(self, question, ranked, reserve=()) -> Retrieval:
        from comparacao.graph_selection import POOL, accept_extras
        from parent_context import expand_parents
        seeds = proxy_seeds(self.table_proxy, ranked)
        found = self.expander.candidates(seeds, question, POOL)
        seen = {item.node_id for item in seeds}
        candidates = []
        for item in found:
            if item.node_id not in seen:
                seen.add(item.node_id)
                item.node.metadata["graph_origin"] = "label"
                candidates.append(item)
        extras, diagnostics = accept_extras(question, list(ranked), candidates, self.reranker,
                                            self.settings["max_per_table"])
        filler = fill_with_reserve(extras, reserve, self.settings.get("baseline_extra_slots", 0))
        return Retrieval([as_result(item) for item in expand_parents(list(ranked) + extras + filler)],
                         {"lexical": diagnostics, "extras_from_reserve": [item.node_id for item in filler]})


class ParentsVariant:
    """Ablação: os mesmos pais literais do GraphRAG, sem nenhum vizinho do grafo."""

    graph_extraction = "disabled"

    def __init__(self, nodes, client, settings, artifacts):
        pass

    def retrieve(self, question, ranked, reserve=()) -> Retrieval:
        from parent_context import expand_parents
        return Retrieval([as_result(item) for item in expand_parents(ranked)])


# simple_rag e graph_rag são as versões comparadas no TCC; parent_rag é ablação.
FROZEN = ("simple_rag", "graph_rag")
REGISTRY = {"simple_rag": SimpleVariant, "graph_rag": GraphVariant, "parent_rag": ParentsVariant,
            "lexical_rag": LexicalVariant}
