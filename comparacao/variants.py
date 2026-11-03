"""Estratégias de recuperação comparadas sobre o mesmo ranking inicial.

As duas variantes recebem os mesmos nós e os mesmos trechos iniciais; só muda o
que acontece depois. Os imports do GraphRAG são tardios porque dependem de
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
    """Sem grafo: usa exatamente os trechos da busca vetorial."""

    graph_extraction = "disabled"

    def __init__(self, nodes, client, settings, artifacts):
        pass

    def retrieve(self, question, ranked) -> Retrieval:
        return Retrieval([as_result(item) for item in ranked])


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

    def retrieve(self, question, ranked) -> Retrieval:
        from community_search import is_global_question
        if is_global_question(question):
            return self._global(question)
        from parent_context import expand_parents
        extras, diagnostics = self._expand(question, ranked)
        return Retrieval([as_result(item) for item in expand_parents(list(ranked) + extras)], {"graph": diagnostics})

    def candidates(self, question, ranked):
        """Candidatos do grafo sem repetição nem sementes, marcados com a origem."""
        from comparacao.graph_selection import POOL
        seen = {item.node_id for item in ranked}
        pools = (("entity", self.graph.retrieve_entity_context(ranked, question)),
                 ("label", self.graph.label_candidates(ranked, question, POOL)),
                 ("documentary", self.graph.retrieve_context(ranked, self.settings["graph_context_limit"])),
                 ("query", self.graph.retrieve(question, exclude_ids=seen)[:POOL]))
        found = []
        for origin, items in pools:
            for item in items:
                if item.node_id not in seen:
                    seen.add(item.node_id)
                    item.node.metadata["graph_origin"] = origin
                    found.append(item)
        return found

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

    def retrieve(self, question, ranked) -> Retrieval:
        from parent_context import expand_parents
        return Retrieval([as_result(item) for item in expand_parents(ranked)])


# rag_simples e graphrag são as versões comparadas no TCC; rag_pais é ablação.
FROZEN = ("rag_simples", "graphrag")
REGISTRY = {"rag_simples": SimpleVariant, "graphrag": GraphVariant, "rag_pais": ParentsVariant}
