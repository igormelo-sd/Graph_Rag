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
        diagnostics = {"reserve_ids": [item.node_id for item in extras]}
        return Retrieval([as_result(item) for item in expand_parents(list(ranked) + extras)], diagnostics)


class GraphVariant:
    """Com grafo: candidatos do grafo escolhidos pelo reranker, pais e, em perguntas globais, comunidades.

    O grafo propõe candidatos a partir dos trechos iniciais (entidades raras em
    comum, trechos da mesma tabela ou documento com rótulos raros da pergunta,
    título, notas e continuidade do texto) e da própria pergunta (observações
    por recorte); o reranker decide quais entram (comparacao/graph_selection.py).
    O ranking inicial não muda.
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
        # Uma linha de cada tabela do índice, usada como semente de apoio das linhas exatas do corpus inteiro.
        self.table_proxy = {}
        for node in nodes:
            if node.metadata.get("type") == "table":
                self.table_proxy.setdefault((str(node.metadata.get("source_file")), str(node.metadata.get("page"))), node)

    def retrieve(self, question, ranked, reserve=()) -> Retrieval:
        from community_search import is_global_question
        if is_global_question(question):
            return self._global(question)
        from parent_context import expand_parents
        extras, diagnostics = self._expand(question, ranked)
        return Retrieval([as_result(item) for item in expand_parents(list(ranked) + extras)], {"graph": diagnostics})

    def candidates(self, question, ranked):
        """Candidatos do grafo sem repetição nem sementes, marcados com a origem.

        O pool de entidades raras ficou de fora: na rodada v4_dev_20261112_r1 propôs 122
        candidatos e o reranker aceitou 2, ao custo de pontuar todos eles.
        """
        from comparacao.graph_selection import POOL
        seeds = self.seeds(ranked)
        seen = {item.node_id for item in seeds}
        pools = (("label", self.graph.label_candidates(seeds, question, POOL)),
                 ("documentary", self.graph.retrieve_context(seeds, self.settings["graph_context_limit"])),
                 ("query", self.graph.retrieve(question, exclude_ids=seen)[:POOL]))
        found = []
        for origin, items in pools:
            for item in items:
                if item.node_id not in seen:
                    seen.add(item.node_id)
                    item.node.metadata["graph_origin"] = origin
                    found.append(item)
        return found

    def seeds(self, ranked):
        """Trechos iniciais mais, para cada linha exata do corpus inteiro, uma linha da mesma tabela no grafo.

        Linhas encontradas fora do índice não existem no grafo; a tabela delas existe, e é por ela
        que chegam notas, título e dicionário. Os apoios não entram no contexto, só guiam a expansão.
        """
        from llama_index.core.schema import NodeWithScore
        present = {item.node_id for item in ranked}
        proxies = []
        for item in ranked:
            if str(item.metadata.get("retrieval_method", "")).startswith("structured"):
                key = (str(item.metadata.get("source_file")), str(item.metadata.get("sheet") or "Planilha"))
                proxy = self.table_proxy.get(key)
                if proxy is not None and proxy.node_id not in present:
                    present.add(proxy.node_id)
                    proxies.append(NodeWithScore(node=proxy, score=0.0))
        return list(ranked) + proxies

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
REGISTRY = {"simple_rag": SimpleVariant, "graph_rag": GraphVariant, "parent_rag": ParentsVariant}
