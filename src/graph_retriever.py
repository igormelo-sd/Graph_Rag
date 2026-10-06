"""
Graph Retriever — recupera nós de texto via travessia do grafo de conhecimento.

Consulta observações por dimensões e hierarquia, percorre contexto documental
e, opcionalmente, usa LLMSynonymRetriever. Retorna chunks com caminhos de apoio.

Deduplicação: remove nós já presentes no contexto de outros retrievers para
evitar repetição de conteúdo na síntese.
"""
import os
import json
from collections import defaultdict, deque
from copy import deepcopy
from domain_ontology import facets, expand_query, filter_candidates, fold
from knowledge_analytics import hierarchy_scope
from runtime import bounded_int
from llama_index.core.schema import NodeWithScore

from llama_index.core.indices.property_graph import LLMSynonymRetriever
from logger import get_logger

log = get_logger(__name__)


class GraphRetriever:
    """
    Recuperação local e LLM opcional, com índices de dimensões e arestas por processo.
    """

    def __init__(self, graph_index, llm, use_llm=True):
        self._store = graph_index.property_graph_store
        self._retriever = LLMSynonymRetriever(
            graph_store=graph_index.property_graph_store,
            include_text=True,
            max_keywords=10,
            path_depth=2,
            llm=llm,
        ) if use_llm else None
        self._outgoing, self._incoming = defaultdict(list), defaultdict(list)
        from llama_index.core.graph_stores.types import ChunkNode
        self._chunk_ids = {node_id for node_id, entity in self._store.graph.nodes.items() if isinstance(entity, ChunkNode)}
        for relation in self._store.graph.relations.values():
            self._outgoing[relation.source_id].append(relation)
            self._incoming[relation.target_id].append(relation)
        self._observations = {}
        self._dimensions = defaultdict(lambda: defaultdict(set))
        self._entity_lookup = defaultdict(lambda: defaultdict(set))
        self._entity_names = {}
        for entity in self._store.graph.nodes.values():
            if entity.label in {"Indicador", "Setor", "FonteDados", "Territorio", "Estado", "Municipio", "Região", "Período"}:
                name = str(getattr(entity, "name", "")).split(":", 1)[-1]
                self._entity_names[entity.id] = fold(name)
                for key, values in facets(name).items():
                    for value in values:
                        self._entity_lookup[key][value].add(entity.id)
            if entity.label != "ObservacaoEstatistica":
                continue
            try:
                dimensions = json.loads(entity.properties.get("dimensions_json", "{}"))
            except (TypeError, ValueError):
                continue
            self._observations[entity.id] = entity
            for key, values in dimensions.items():
                if len(values) != 1:
                    continue
                for value in values:
                    self._dimensions[key][value].add(entity.id)

    def retrieve(self, question: str, exclude_ids: set | None = None) -> list:
        """
        Retorna nós de texto recuperados via grafo.

        Parâmetros
        ----------
        question : str
            Query (reescrita pelo interpreter).
        exclude_ids : set | None
            IDs de nós já presentes em outros retrievers — serão filtrados
            para evitar duplicação no contexto.

        Retorna
        -------
        list[NodeWithScore] com conteúdo não-vazio e não-duplicado.
        """
        nodes = self._retrieve_observations(question)
        nodes.extend(self._retrieve_relations(question))
        try:
            if self._retriever is not None:
                nodes.extend(self._retriever.retrieve(expand_query(question)))
        except Exception as exc:
            log.warning("[Graph] Falha no retrieval: %s", exc)
        nodes = filter_candidates(nodes, question)

        seen = set(exclude_ids or ())
        result = []
        by_id = {}
        for n in nodes:
            nid = getattr(n.node, "node_id", None) or id(n)
            if nid not in seen and n.get_content().strip():
                result.append(n)
                seen.add(nid)
                by_id[nid] = n
            elif nid in by_id and n.metadata.get("graph_paths"):
                previous = by_id[nid]
                paths = json.loads(previous.metadata.get("graph_paths", "[]")) + json.loads(n.metadata["graph_paths"])
                previous.metadata["graph_paths"] = json.dumps(list({json.dumps(path, sort_keys=True): path for path in paths}.values())[:40], ensure_ascii=False)

        log.info("[Graph] %d nós recuperados pelo grafo", len(result))
        return result

    def _retrieve_relations(self, question):
        """Busca local por entidades/aliases em relações auditadas, sem gerar novos fatos."""
        wanted = facets(question)
        seeds = set()
        for key, values in wanted.items():
            for value in values:
                seeds |= self._entity_lookup[key].get(value, set())
        normalized = fold(question)
        seeds |= {node_id for node_id, name in self._entity_names.items() if len(name) >= 4 and name in normalized}
        allowed = {"RELACIONA_COM", "ASSOCIADO_A", "CAUSA", "MEDIDO_POR", "CRESCEU_EM", "RECUOU_EM", "APLICA_SE_A", "NO_SETOR", "PERTENCE_A"}
        pending = deque((seed, 0, []) for seed in sorted(seeds)[:20])
        visited, sources, paths, edges_seen = set(), [], defaultdict(list), 0
        while pending and edges_seen < 160:
            current, depth, path = pending.popleft()
            if current in visited or depth >= 2:
                continue
            visited.add(current)
            for relation in self._outgoing.get(current, []) + self._incoming.get(current, []):
                if relation.label not in allowed:
                    continue
                edges_seen += 1
                if edges_seen > 160:
                    break
                source = relation.properties.get("source_node_id")
                # Exige a proveniência registrada pelo extrator, não apenas uma aresta solta.
                if not source or source not in self._chunk_ids:
                    continue
                step = {"source": relation.source_id, "relation": relation.label, "target": relation.target_id,
                        "evidence": relation.properties.get("evidence", ""), "modality": relation.properties.get("modality"),
                        "relation_kind": relation.properties.get("relation_kind"), "semantic_status": "requires_review"}
                extended = path + [step]
                if source not in sources and len(sources) < 20:
                    sources.append(source)
                if source in sources:
                    paths[source].extend(extended)
                other = relation.target_id if relation.source_id == current else relation.source_id
                pending.append((other, depth + 1, extended))
        return [self._with_paths(node, paths[node.node_id], 0.45) for node in self._store.get_llama_nodes(sources)]

    def _retrieve_observations(self, question):
        """Consulta dimensões explícitas do grafo e recupera os chunks de origem."""
        wanted = facets(question)
        scope = hierarchy_scope(question)
        keys = [k for k in ("indicator", "region", "period", "unit", "scale", "sector", "source", "kind", "basis", "coverage")
                if wanted[k] or scope.get(k + "_requested")]
        if not keys:
            return []
        candidates = None
        for key in keys:
            if scope.get(key + "_requested"):
                matched = set().union(*(self._dimensions[key].get(value, set()) for value in scope[key]))
            else:
                matched = set().union(*(self._dimensions[key].get(value, set()) for value in wanted[key]))
            candidates = matched if candidates is None else candidates & matched
        source_ids, paths = [], defaultdict(list)
        for observation_id in sorted(candidates or ()):
            entity = self._observations[observation_id]
            for relation in self._outgoing.get(observation_id, ()):
                if relation.label != "SUSTENTADA_POR":
                    continue
                source = relation.target_id
                if source not in source_ids:
                    if len(source_ids) >= 20:
                        continue
                    source_ids.append(source)
                paths[source].append({"source": observation_id, "relation": relation.label, "target": source})
                paths[source].extend(self._hierarchy_paths(observation_id, scope, wanted))
        return [self._with_paths(n, paths[n.node_id], 0.5) for n in self._store.get_llama_nodes(source_ids)]

    def _hierarchy_paths(self, observation_id, scope, wanted):
        paths = []
        for key, label in (("region", "APLICA_SE_A"), ("sector", "NO_SETOR")):
            if not scope.get(key + "_requested"):
                continue
            for edge in self._outgoing.get(observation_id, ()):
                if edge.label != label:
                    continue
                paths.append({"source": edge.source_id, "relation": edge.label, "target": edge.target_id})
                current = edge.target_id
                visited = set()
                while current not in visited and len(visited) < 8:
                    visited.add(current)
                    node = self._store.graph.nodes.get(current)
                    if node is None or node.properties.get("canonical_id") in wanted[key]:
                        break
                    parent_edges = [relation for relation in self._outgoing.get(current, ()) if relation.label == "PARTE_DE"]
                    if len(parent_edges) != 1:
                        break
                    parent = parent_edges[0]
                    paths.append({"source": parent.source_id, "relation": parent.label, "target": parent.target_id,
                                  "method": parent.properties.get("method", "registered_hierarchy")})
                    current = parent.target_id
        return paths

    @staticmethod
    def _with_paths(node, paths, score):
        node = deepcopy(node)
        node.metadata["graph_paths"] = json.dumps(paths[:20], ensure_ascii=False)
        node.excluded_embed_metadata_keys = list(dict.fromkeys(node.excluded_embed_metadata_keys + ["graph_paths"]))
        node.excluded_llm_metadata_keys = list(dict.fromkeys(node.excluded_llm_metadata_keys + ["graph_paths"]))
        return NodeWithScore(node=node, score=score)

    def retrieve_context(self, nodes, max_nodes=6):
        """Percorre arestas documentais com prioridade às notas e orçamento limitado."""
        max_nodes = min(max_nodes, bounded_int("RAG_GRAPH_CONTEXT_LIMIT", 6, 1, 30))
        depth_limit = bounded_int("RAG_GRAPH_CONTEXT_DEPTH", 2, 1, 3)
        allowed = {"TEM_NOTA": 0, "TEM_TITULO": 1, "DESCRITA_EM": 2, "REPRESENTADA_EM": 3, "NEXT_CHUNK": 4, "SAME_PAGE": 5}
        original = {str(getattr(getattr(n, "node", n), "node_id", "")) for n in nodes}
        pending = deque((node_id, 0, []) for node_id in sorted(original))
        visited = set(original)
        paths, visits = {}, 0
        while pending and visits < 160:
            current, depth, path = pending.popleft()
            if depth >= depth_limit:
                continue
            edges = self._outgoing.get(current, []) + self._incoming.get(current, [])
            for relation in sorted(edges, key=lambda edge: (allowed.get(edge.label, 99), edge.source_id, edge.target_id)):
                if relation.label not in allowed:
                    continue
                visits += 1
                if visits > 160:
                    break
                target = relation.target_id if relation.source_id == current else relation.source_id
                if target in visited:
                    continue
                visited.add(target)
                step = {"source": relation.source_id, "relation": relation.label, "target": relation.target_id,
                        "method": relation.properties.get("method", "document_structure"),
                        "semantic_status": relation.properties.get("semantic_status", "documentary_link")}
                extended = path + [step]
                paths[target] = extended
                # Não expandir indefinidamente adjacência nem incluir todos os chunks da página.
                if relation.label not in {"NEXT_CHUNK", "SAME_PAGE"}:
                    pending.append((target, depth + 1, extended))
        if not paths:
            return []
        candidates = self._store.get_llama_nodes([target for target in paths if target in self._chunk_ids])
        candidates = sorted(candidates, key=lambda n: (min(allowed[s["relation"]] for s in paths[n.node_id]), len(paths[n.node_id]), n.node_id))
        return [self._with_paths(n, paths[n.node_id], 0.45) for n in candidates[:max_nodes] if n.node_id not in original]

    def retrieve_neighbors(self, nodes: list, db_path: str | None = None, limit_per_node: int = 1) -> list:
        """Costura contexto dividido: traz NEXT_CHUNK/SAME_PAGE vizinhos (determinístico, sem LLM)."""
        if not nodes:
            return []
        graph_context = self.retrieve_context(nodes, min(6, max(1, len(nodes) * limit_per_node)))
        if graph_context:
            return graph_context
        try:
            from indexing import load_nodes_cache
            from index_manifest import resolve_db_dir

            if db_path is None:
                try:
                    db_path = resolve_db_dir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                except Exception:
                    db_path = "./chroma_db"
            all_nodes = load_nodes_cache(db_path)
            if not all_nodes:
                return []
            # índice por (source_file, page, chunk_id)
            idx: dict[tuple, object] = {}
            for n in all_nodes:
                md = getattr(n, "metadata", {}) or {}
                if md.get("type", "text") != "text":
                    continue
                key = (str(md.get("source_file") or ""), str(md.get("page") or ""), str(md.get("chunk_id") or ""))
                idx[key] = n
            neighbors = []
            seen = set()
            for n in nodes:
                md = getattr(n, "metadata", {}) or {}
                if md.get("type", "text") != "text":
                    continue
                src, page, cid = str(md.get("source_file") or ""), str(md.get("page") or ""), md.get("chunk_id")
                if cid is None:
                    continue
                try:
                    cid_int = int(cid)
                except Exception:
                    continue
                for delta in (-1, 1):
                    key = (src, page, str(cid_int + delta))
                    nb = idx.get(key)
                    if nb is not None:
                        nid = getattr(getattr(nb, "node", nb), "node_id", None) or id(nb)
                        if nid not in seen:
                            # limita 1 vizinho por direção
                            neighbors.append(nb)
                            seen.add(nid)
                            if len(neighbors) >= len(nodes) * limit_per_node:
                                break
                if len(neighbors) >= len(nodes) * limit_per_node:
                    break
            if neighbors:
                log.info("[Graph] Costura: %d vizinhos NEXT_CHUNK/SAME_PAGE", len(neighbors))
            return neighbors
        except Exception as exc:
            log.warning("[Graph] Falha ao costurar vizinhos: %s", exc)
            return []
