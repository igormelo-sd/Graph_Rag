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
    """Com grafo: entidades, vizinhança estrutural, pais e, em perguntas globais, comunidades."""

    graph_extraction = "registered_entities_only"

    def __init__(self, nodes, client, settings, artifacts):
        # Construído antes da cronometragem, como o carregamento dos modelos.
        from llama_index.core.graph_stores import SimplePropertyGraphStore
        from graph_indexing import inject_deterministic_triplets
        from graph_retriever import GraphRetriever
        self.nodes, self.client, self.settings = nodes, client, settings
        self.summaries_path = artifacts / "community_summaries.json"
        self.store = SimplePropertyGraphStore()
        inject_deterministic_triplets(self.store, nodes, structural=True)
        self.graph = GraphRetriever(SimpleNamespace(property_graph_store=self.store), None, use_llm=False)

    def retrieve(self, question, ranked) -> Retrieval:
        from community_search import is_global_question
        if is_global_question(question):
            return self._global(question)
        from parent_context import expand_parents
        return Retrieval([as_result(item) for item in expand_parents(self._expand(question, ranked))])

    def _expand(self, question, ranked):
        """Acrescenta vizinhos do grafo após o ranking inicial, sem reordená-lo."""
        extra = self.graph.retrieve_entity_context(ranked, question)
        extra += self.graph.retrieve_context(ranked, self.settings["graph_context_limit"])
        expanded, seen = list(ranked), {item.node_id for item in ranked}
        for item in extra:
            if item.node_id not in seen:
                seen.add(item.node_id)
                expanded.append(item)
        return expanded

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


class GraphV2Variant(GraphVariant):
    """Experimental: vizinhos escolhidos por relevância; ver comparacao/graph_v2.py."""

    uses_reranker = True

    def __init__(self, nodes, client, settings, artifacts, reranker=None):
        super().__init__(nodes, client, settings, artifacts)
        self.reranker = reranker

    def _expand(self, question, ranked):
        from domain_ontology import filter_candidates
        from comparacao.graph_v2 import ENTITY_POOL, QUERY_POOL, accept_extras, document_context, entity_candidates
        seeds = [item.node_id for item in ranked]
        seen = set(seeds)

        def wrap(identities, paths, score, origin):
            order = {identity: position for position, identity in enumerate(identities)}
            nodes = [node for node in self.graph._get_source_nodes(identities) if node.node_id not in seen]
            wrapped = [self.graph._with_paths(node, paths[node.node_id], score) for node in nodes]
            for item in wrapped:
                item.node.metadata["graph_v2_origin"] = origin
            seen.update(item.node_id for item in wrapped)
            return sorted(wrapped, key=lambda item: order[item.node_id])

        context = document_context(self.graph, seeds, self.settings["graph_context_limit"])
        documentary = wrap([key for key, _ in context], dict(context), 0.45, "documentary")
        by_entity = entity_candidates(self.graph, seeds, ENTITY_POOL)
        candidates = filter_candidates(wrap([key for key, _, _ in by_entity],
                                            {key: path for key, _, path in by_entity}, 0.4, "entity"), question)
        guided = [item for item in self.graph.retrieve(question, exclude_ids=seen)][:QUERY_POOL]
        for item in guided:
            item.node.metadata["graph_v2_origin"] = "query"
        seen.update(item.node_id for item in guided)
        accepted, diagnostics = accept_extras(question, list(ranked), candidates + guided, self.reranker,
                                              self.settings["max_per_table"])
        self.last_diagnostics = {"graph_v2": {**diagnostics, "documentary": [item.node_id for item in documentary],
                                              "entity_pool": len(candidates), "query_pool": len(guided)}}
        return list(ranked) + documentary + accepted

    def retrieve(self, question, ranked) -> Retrieval:
        self.last_diagnostics = {}
        retrieval = super().retrieve(question, ranked)
        retrieval.diagnostics.update(self.last_diagnostics)
        return retrieval


# rag_simples e graphrag são as versões congeladas em 28/10/2026; as demais são experimentais.
FROZEN = ("rag_simples", "graphrag")
REGISTRY = {"rag_simples": SimpleVariant, "graphrag": GraphVariant,
            "rag_pais": ParentsVariant, "graphrag_v2": GraphV2Variant}
