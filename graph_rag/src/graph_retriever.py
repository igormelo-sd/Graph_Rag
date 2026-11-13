"""
Graph Retriever — recupera nós de texto via travessia do grafo de conhecimento.

Consulta observações por dimensões e hierarquia, percorre contexto documental
e, opcionalmente, usa LLMSynonymRetriever. Retorna chunks com caminhos de apoio.

Deduplicação: remove nós já presentes no contexto de outros retrievers para
evitar repetição de conteúdo na síntese.
"""
import os
import json
import math
import re
from collections import defaultdict, deque

import networkx as nx
from copy import deepcopy
from domain_ontology import facets, expand_query, filter_candidates, fold
from knowledge_analytics import hierarchy_scope
from runtime import bounded_float, bounded_int
from llama_index.core.schema import NodeWithScore

from llama_index.core.indices.property_graph import LLMSynonymRetriever
from logger import get_logger
from relation_semantics import CO_DIMENSION

log = get_logger(__name__)

_TERM = re.compile(r"\d+(?:[.,/-]\d+)*[a-z]?|[a-z]{3,}")
_STOPWORDS = frozenset(
    "com das dos entre foi nas nos para pela pelas pelo pelos por qual quais que sua suas seu seus uma "
    "como quanto quanta quantos quantas onde quando sobre segundo valor".split())


def _terms(text):
    """Termos sem acento para casar rótulos de tabela; números e anos ficam inteiros."""
    return {term for term in _TERM.findall(fold(str(text))) if term not in _STOPWORDS}


def _seed_ids(nodes):
    """IDs das sementes na ordem recebida, que carrega a prioridade do ranking."""
    return list(dict.fromkeys(str(getattr(getattr(n, "node", n), "node_id", "")) for n in nodes))


class GraphRetriever:
    """
    Recuperação local e LLM opcional, com índices de dimensões e arestas por processo.
    """


    def _get_source_nodes(self, identities):
        """Lista vazia significa ausência de fontes, nunca consulta sem filtro."""
        identities = list(identities)
        if not identities:
            return []
        # Preserva a ordem pedida: ela carrega a prioridade calculada pelo chamador.
        order = {identity: position for position, identity in enumerate(identities)}
        return sorted((node for node in self._store.get_llama_nodes(identities) if node.node_id in order),
                      key=lambda node: order[node.node_id])


    def _out(self, node):
        """Relações que saem de `node` (vazio se o nó não está no grafo)."""
        return [data["relation"] for _, _, data in self._graph.out_edges(node, data=True)] if node in self._graph else []

    def _in(self, node):
        """Relações que chegam a `node`."""
        return [data["relation"] for _, _, data in self._graph.in_edges(node, data=True)] if node in self._graph else []

    def __init__(self, graph_index, llm, use_llm=True):
        self._store = graph_index.property_graph_store
        self._retriever = LLMSynonymRetriever(
            graph_store=graph_index.property_graph_store,
            include_text=True,
            max_keywords=10,
            path_depth=2,
            llm=llm,
        ) if use_llm else None
        from llama_index.core.graph_stores.types import ChunkNode
        self._chunk_ids = {node_id for node_id, entity in self._store.graph.nodes.items() if isinstance(entity, ChunkNode)}
        # O armazenamento do LlamaIndex guarda nós e relações; o grafo para percorrer e calcular é do NetworkX.
        self._graph = nx.MultiDiGraph()
        self._graph.add_nodes_from(self._store.graph.nodes)
        for key, relation in self._store.graph.relations.items():
            self._graph.add_edge(relation.source_id, relation.target_id, key=key, relation=relation)
        self._mention_cache, self._term_cache = {}, {}
        self._document_chunks = self._chunk_document = None
        self._observations = {}
        self._observation_dimensions = {}
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
            self._observation_dimensions[entity.id] = dimensions
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
        allowed = {"RELACIONA_COM", "ASSOCIADO_A", "CAUSA", "MEDIDO_POR", "CRESCEU_EM", "RECUOU_EM", "APLICA_SE_A", "NO_SETOR"}
        pending = deque((seed, 0, []) for seed in sorted(seeds)[:20])
        visited, sources, paths, edges_seen = set(), [], defaultdict(list), 0
        while pending and edges_seen < 160:
            current, depth, path = pending.popleft()
            if current in visited or depth >= 2:
                continue
            visited.add(current)
            for relation in self._out(current) + self._in(current):
                # Co-dimensões ligam entidades; a fonte registrada é só uma das células.
                if relation.label not in allowed or relation.properties.get("semantic_status") == CO_DIMENSION:
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
                        "polarity": relation.properties.get("polarity", "affirmed"),
                        "relation_kind": relation.properties.get("relation_kind"), "semantic_status": "requires_review"}
                extended = path + [step]
                if source not in sources and len(sources) < 20:
                    sources.append(source)
                if source in sources:
                    paths[source].extend(extended)
                other = relation.target_id if relation.source_id == current else relation.source_id
                pending.append((other, depth + 1, extended))
        return [self._with_paths(node, paths[node.node_id], 0.45) for node in self._get_source_nodes(sources)]

    def _retrieve_observations(self, question):
        """Consulta dimensões explícitas do grafo e recupera os chunks de origem."""
        wanted = facets(question)
        scope = hierarchy_scope(question)
        # Recortes obrigatórios são os mesmos de filter_candidates; os demais só ordenam.
        required = [k for k in self._REQUIRED if wanted[k] or scope.get(k + "_requested")]
        preferred = [k for k in self._PREFERRED if wanted[k]]
        keys = required or preferred
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
        ranked = sorted(candidates or (), key=lambda identity: self._observation_rank(identity, wanted, preferred))
        for observation_id in ranked:
            for relation in self._out(observation_id):
                if relation.label != "SUSTENTADA_POR":
                    continue
                source = relation.target_id
                if source not in source_ids:
                    if len(source_ids) >= 20:
                        continue
                    source_ids.append(source)
                paths[source].append({"source": observation_id, "relation": relation.label, "target": source})
                paths[source].extend(self._hierarchy_paths(observation_id, scope, wanted))
        return [self._with_paths(n, paths[n.node_id], 0.5) for n in self._get_source_nodes(source_ids)]

    def retrieve_gaps(self, question, missing, exclude_ids=(), limit=6):
        """Observações para cada recorte pedido que o contexto ainda não sustenta.

        `missing` mapeia indicador, território, período ou setor (identificadores canônicos) aos valores
        da pergunta sem apoio nos trechos já escolhidos. Para cada um, busca observações com esse valor
        e os demais recortes obrigatórios da pergunta, até dois trechos de origem por valor. Não afirma
        compatibilidade: só traz de volta o trecho que sustenta o recorte.
        """
        wanted = facets(question)
        preferred = [k for k in self._PREFERRED if wanted[k]]
        seen, sources, paths = set(exclude_ids), [], {}
        for key, values in missing.items():
            for value in values:
                candidates = set(self._dimensions[key].get(value, set()))
                for other in self._REQUIRED:
                    if other != key and wanted[other]:
                        candidates &= set().union(*(self._dimensions[other].get(v, set()) for v in wanted[other]))
                taken = 0
                for observation_id in sorted(candidates, key=lambda i: self._observation_rank(i, wanted, preferred)):
                    for relation in self._out(observation_id):
                        if relation.label != "SUSTENTADA_POR" or relation.target_id in seen:
                            continue
                        seen.add(relation.target_id)
                        sources.append(relation.target_id)
                        paths[relation.target_id] = [{"source": observation_id, "relation": "SUSTENTADA_POR",
                                                      "target": relation.target_id, "method": "coverage_gap",
                                                      "gap": f"{key}:{value}"}]
                        taken += 1
                    if taken >= 2:
                        break
        found = [self._with_paths(n, paths[n.node_id], 0.5) for n in self._get_source_nodes(sources)]
        return filter_candidates(found, question)[:limit]

    # Peso de cada tipo de relação na projeção usada pelo PageRank; as demais (entidades e dimensões das
    # observações) pesam menos, e as arestas para nós muito conectados são amortecidas pelo grau.
    _PPR_WEIGHTS = {"CONTIDA_EM": 1.0, "PERTENCE_A_DOC": 0.4, "REPRESENTADA_EM": 1.0, "NEXT_CHUNK": 1.0, "SAME_PAGE": 0.3,
                    "TEM_NOTA": 1.0, "TEM_TITULO": 1.0, "DESCRITA_EM": 1.0, "DICIONARIO_DE": 1.0, "SUSTENTADA_POR": 1.0}
    _PPR_DEFAULT = 0.4

    def _ppr_graph(self):
        """Projeção não direcionada e ponderada do grafo, construída uma vez por processo."""
        if getattr(self, "_ppr_cache", None) is None:
            graph = nx.DiGraph()
            for source, target, data in self._graph.edges(data=True):
                base = self._PPR_WEIGHTS.get(data["relation"].label, self._PPR_DEFAULT)
                for origin, destination in ((source, target), (target, source)):
                    weight = base / math.log2(2 + self._graph.degree(destination))
                    previous = graph.get_edge_data(origin, destination, {}).get("weight", 0.0)
                    graph.add_edge(origin, destination, weight=previous + weight)
            self._ppr_cache = graph
        return self._ppr_cache

    def retrieve_ppr(self, nodes, question, limit=8, alpha=0.6):
        """Trechos mais próximos das sementes na estrutura do grafo, por PageRank personalizado.

        A massa parte das sementes (a primeira vale mais) e se espalha por tabelas, páginas, documentos,
        notas, dicionários, observações e entidades; os trechos com mais massa, fora as sementes, são os
        candidatos. Multi-salto, ao contrário da expansão por rótulos, que só olha a mesma tabela ou documento.
        """
        graph = self._ppr_graph()
        seeds = [seed for seed in _seed_ids(nodes) if seed in graph]
        if not seeds:
            return []
        personalization = {seed: 1.0 / (rank + 1) for rank, seed in enumerate(seeds)}
        scores = nx.pagerank(graph, alpha=alpha, personalization=personalization, weight="weight", max_iter=100, tol=1e-6)
        original = set(seeds)
        ranked = sorted((chunk for chunk in self._chunk_ids if chunk not in original and scores.get(chunk, 0.0) > 0),
                        key=lambda chunk: (-scores[chunk], chunk))[:limit * 4]
        if not ranked:
            return []
        top = scores[ranked[0]]
        found = [self._with_paths(node, [{"relation": "PPR", "method": "personalized_pagerank",
                                          "score": round(scores[node.node_id], 8), "semantic_status": "documentary_link"}],
                                  round(0.4 * scores[node.node_id] / top, 4))
                 for node in self._get_source_nodes(ranked)]
        return filter_candidates(found, question)[:limit]

    _REQUIRED = ("indicator", "region", "period", "unit", "scale", "sector")
    _PREFERRED = ("source", "kind", "basis", "coverage")

    def _observation_rank(self, observation_id, wanted, preferred):
        """Menos conflitos e mais recortes atendidos primeiro; candidatos completos antes dos pendentes."""
        dimensions = self._observation_dimensions.get(observation_id, {})
        conflicts = matches = 0
        for key in preferred:
            got = set(dimensions.get(key, []))
            if got & wanted[key]:
                matches += 1
            elif got:
                conflicts += 1
        entity = self._observations[observation_id]
        try:
            issues = len(json.loads(entity.properties.get("issues_json", "[]")))
        except (TypeError, ValueError):
            issues = 99
        return (conflicts, -matches, entity.properties.get("status") != "structured_candidate", issues, observation_id)

    def _hierarchy_paths(self, observation_id, scope, wanted):
        paths = []
        for key, label in (("region", "APLICA_SE_A"), ("sector", "NO_SETOR")):
            if not scope.get(key + "_requested"):
                continue
            for edge in self._out(observation_id):
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
                    parent_edges = [relation for relation in self._out(current) if relation.label == "PARTE_DE"]
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
        """Percorre arestas documentais com prioridade às notas e orçamento limitado.

        A tabela é ponte para título, notas e descrições: as linhas irmãs não entram
        por aqui (veja label_candidates). Empates seguem a ordem das sementes.
        """
        max_nodes = min(max_nodes, bounded_int("RAG_GRAPH_CONTEXT_LIMIT", 6, 1, 30))
        depth_limit = bounded_int("RAG_GRAPH_CONTEXT_DEPTH", 2, 1, 3)
        allowed = {"TEM_NOTA": 0, "TEM_TITULO": 1, "DESCRITA_EM": 2, "DICIONARIO_DE": 2, "REPRESENTADA_EM": 3, "NEXT_CHUNK": 4, "SAME_PAGE": 5}
        seeds = _seed_ids(nodes)
        original = set(seeds)
        pending = deque((node_id, 0, [], rank) for rank, node_id in enumerate(seeds))
        visited = set(original)
        paths, origin, visits = {}, {}, 0
        while pending and visits < 160:
            current, depth, path, rank = pending.popleft()
            if depth >= depth_limit:
                continue
            edges = self._out(current) + self._in(current)
            for relation in sorted(edges, key=lambda edge: (allowed.get(edge.label, 99), edge.source_id, edge.target_id)):
                if relation.label not in allowed:
                    continue
                if relation.label == "REPRESENTADA_EM" and current not in self._chunk_ids:
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
                origin[target] = rank
                # Não expandir indefinidamente adjacência nem incluir todos os chunks da página.
                if relation.label not in {"NEXT_CHUNK", "SAME_PAGE"}:
                    pending.append((target, depth + 1, extended, rank))
        if not paths:
            return []
        candidates = self._get_source_nodes([target for target in paths if target in self._chunk_ids])
        candidates = sorted(candidates, key=lambda n: (min(allowed[s["relation"]] for s in paths[n.node_id]),
                                                       origin[n.node_id], len(paths[n.node_id]), n.node_id))
        return [self._with_paths(n, paths[n.node_id], 0.45) for n in candidates[:max_nodes] if n.node_id not in original]

    def _mentions(self, entity):
        if entity not in self._mention_cache:
            self._mention_cache[entity] = [edge.source_id for edge in self._in(entity)
                                           if edge.label == "HAS_ENTITY" and edge.source_id in self._chunk_ids]
        return self._mention_cache[entity]

    def _hub_limit(self):
        """Entidades mencionadas por mais trechos que isso não servem de ponte."""
        share = bounded_float("RAG_ENTITY_HUB_SHARE", 0.02, 0.0, 1.0)
        return max(50, int(share * len(self._chunk_ids)))

    def retrieve_entity_context(self, nodes, question):
        """Trecho -> entidade (-> entidade relacionada) -> outros trechos, por relevância.

        Cada candidato soma, por entidade compartilhada com uma semente, o peso de
        raridade da entidade (IDF suavizado) dividido pela posição da semente;
        entidades alcançadas por relação registrada valem metade a cada passo.
        Entidades acima do limite de hub não servem de ponte. O node_id só desempata.
        """
        from domain_ontology import RELATIONS
        limit = bounded_int("RAG_ENTITY_CONTEXT_LIMIT", 8, 1, 40)
        depth_limit = bounded_int("RAG_ENTITY_CONTEXT_DEPTH", 1, 0, 2)
        seeds = _seed_ids(nodes)
        original, total, hub = set(seeds), max(1, len(self._chunk_ids)), self._hub_limit()
        scores, paths = defaultdict(float), {}
        for rank, seed in enumerate(seeds):
            pending = deque((edge.target_id, 0, 1.0, [{"source": seed, "relation": edge.label,
                             "target": edge.target_id, "semantic_status": "mention_only"}])
                            for edge in self._out(seed) if edge.label == "HAS_ENTITY")
            reached = {}
            while pending:
                entity, depth, weight, path = pending.popleft()
                if entity in reached:
                    continue
                reached[entity] = (weight, path)
                if depth >= depth_limit:
                    continue
                for edge in self._out(entity) + self._in(entity):
                    if (edge.label not in RELATIONS or not edge.properties.get("source_node_id")
                            or edge.properties.get("polarity") == "negated"):
                        continue
                    other = edge.target_id if edge.source_id == entity else edge.source_id
                    if other not in self._chunk_ids and other not in reached:
                        pending.append((other, depth + 1, weight / 2, path + [{"source": edge.source_id,
                            "relation": edge.label, "target": edge.target_id,
                            "evidence": edge.properties.get("evidence", ""),
                            "polarity": edge.properties.get("polarity", "affirmed"),
                            "semantic_status": "requires_review"}]))
            for entity, (weight, path) in reached.items():
                mentions = self._mentions(entity)
                if not mentions or len(mentions) > hub:
                    continue
                gain = weight * math.log(1 + total / len(mentions)) / (rank + 1)
                for chunk in mentions:
                    if chunk in original:
                        continue
                    scores[chunk] += gain
                    paths.setdefault(chunk, path + [{"source": chunk, "relation": "HAS_ENTITY",
                                                     "target": entity, "semantic_status": "mention_only"}])
        if not scores:
            return []
        top = max(scores.values())
        # Filtra antes de cortar: candidatos com recorte conflitante não ocupam vagas.
        ordered = sorted(scores, key=lambda chunk: (-scores[chunk], chunk))[:limit * 4]
        candidates = [self._with_paths(n, paths[n.node_id], round(0.4 * scores[n.node_id] / top, 4))
                      for n in self._get_source_nodes(ordered)]
        return filter_candidates(candidates, question)[:limit]

    def _row_terms(self, chunk_id):
        if chunk_id not in self._term_cache:
            node = self._store.graph.nodes.get(chunk_id)
            self._term_cache[chunk_id] = _terms(getattr(node, "text", "") or "")
        return self._term_cache[chunk_id]

    def _scopes(self, seed):
        """Tabela e documento que contêm a semente, com seus trechos e o caminho até ela."""
        if self._document_chunks is None:
            page_document = {r.source_id: r.target_id for r in self._store.graph.relations.values()
                             if r.label == "PERTENCE_A_DOC"}
            self._document_chunks, self._chunk_document = defaultdict(list), {}
            for relation in self._store.graph.relations.values():
                document = page_document.get(relation.target_id)
                if relation.label == "CONTIDA_EM" and relation.source_id in self._chunk_ids and document:
                    self._document_chunks[document].append(relation.source_id)
                    self._chunk_document[relation.source_id] = (document, relation.target_id)
        for edge in self._in(seed):
            if edge.label == "REPRESENTADA_EM" and edge.source_id not in self._chunk_ids:
                rows = [e.target_id for e in self._out(edge.source_id)
                        if e.label == "REPRESENTADA_EM" and e.target_id in self._chunk_ids]
                yield edge.source_id, rows, [{"source": edge.source_id, "relation": "REPRESENTADA_EM", "target": seed}], "row_label_match"
        if seed in self._chunk_document:
            document, page = self._chunk_document[seed]
            yield document, self._document_chunks[document], [
                {"source": seed, "relation": "CONTIDA_EM", "target": page},
                {"source": page, "relation": "PERTENCE_A_DOC", "target": document}], "document_label_match"

    def label_candidates(self, nodes, question, limit=8):
        """Trechos da tabela ou do documento das sementes que repetem termos raros da pergunta.

        Cada termo vale pela raridade dentro do próprio escopo (log N/df): o título,
        repetido em todas as linhas, não conta. Trechos sem termo raro em comum não
        entram. Complementa o ranking inicial quando o trecho pedido fica fora dos
        candidatos: séries longas com o mesmo título e cabeçalho, ou a tabela-resumo
        do mesmo caderno com o rótulo procurado.
        """
        wanted = _terms(question)
        if not wanted:
            return []
        seeds = _seed_ids(nodes)
        original = set(seeds)
        best, paths, scopes_seen = {}, {}, set()
        for rank, seed in enumerate(seeds):
            for scope, members, bridge, method in self._scopes(seed):
                if scope in scopes_seen or len(members) < 2:
                    continue
                scopes_seen.add(scope)
                frequency = defaultdict(int)
                for member in members:
                    for term in self._row_terms(member) & wanted:
                        frequency[term] += 1
                weight = {term: math.log(len(members) / count) for term, count in frequency.items()}
                for member in members:
                    if member in original:
                        continue
                    matched = sorted(term for term in self._row_terms(member) & wanted if weight[term] > 0)
                    score = sum(weight[term] for term in matched) / (rank + 1)
                    if score > best.get(member, (0.0,))[0]:
                        best[member] = (score, rank)
                        paths[member] = bridge + [{"source": scope, "relation": "CONTEM", "target": member,
                                                   "method": method, "evidence": " ".join(matched),
                                                   "semantic_status": "documentary_link"}]
        if not best:
            return []
        top = max(score for score, _ in best.values())
        ordered = sorted(best, key=lambda row: (-best[row][0], best[row][1], row))[:limit * 4]
        candidates = [self._with_paths(n, paths[n.node_id], round(0.4 * best[n.node_id][0] / top, 4))
                      for n in self._get_source_nodes(ordered)]
        return filter_candidates(candidates, question)[:limit]

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
