"""Seleção experimental de vizinhos do grafo para a variante `graphrag_v2`.

Diferenças em relação a `GraphVariant`, congelada em 28/10/2026:

1. Vizinhos por entidade são pontuados pelas entidades que compartilham com os
   trechos iniciais, com peso de raridade (IDF suavizado) e da posição da semente.
   Na versão congelada a escolha seguia a ordem dos `node_id`.
2. Uma tabela não traz as próprias linhas irmãs (`REPRESENTADA_EM`), que
   contornavam o limite por tabela do ranking inicial; da tabela vêm só título,
   notas e descrições.
3. A busca guiada pela pergunta do `GraphRetriever` (observações por recorte e
   relações auditadas) também fornece candidatos.

Os candidatos de 1 e 3 passam pelo reranker do ranking inicial e só entram acima
de um limiar relativo aos trechos iniciais da mesma pergunta. Os parâmetros
ficam aqui, e não em `config.json`, para não alterar o perfil congelado.
"""
import math
from collections import defaultdict

ENTITY_POOL = 16      # candidatos por entidade levados ao reranker
QUERY_POOL = 16       # candidatos da busca guiada levados ao reranker
EXTRA_LIMIT = 4       # extras aceitos depois do reranker
RELATED_WEIGHT = 0.5  # peso de entidades alcançadas por relação auditada
SCORE_RATIO = 0.5     # fração do menor escore inicial exigida dos extras
SCORE_FLOOR = 0.02
DOCUMENT_RELATIONS = ("TEM_NOTA", "TEM_TITULO", "DESCRITA_EM")


def entity_candidates(graph, seeds, limit=ENTITY_POOL):
    """Trechos que mencionam entidades das sementes, das mais raras às mais comuns.

    Devolve (node_id, pontuação, caminhos) em ordem decrescente de pontuação.
    """
    from domain_ontology import RELATIONS
    seed_set, total = set(seeds), max(1, len(graph._chunk_ids))
    mentions = {}

    def mentioned_by(entity):
        if entity not in mentions:
            mentions[entity] = [edge.source_id for edge in graph._incoming.get(entity, ())
                                if edge.label == "HAS_ENTITY" and edge.source_id in graph._chunk_ids]
        return mentions[entity]

    scores, paths = defaultdict(float), defaultdict(list)
    for rank, seed in enumerate(seeds):
        entities = {edge.target_id: (1.0, [{"source": seed, "relation": "HAS_ENTITY", "target": edge.target_id,
                                            "semantic_status": "mention_only"}])
                    for edge in graph._outgoing.get(seed, ()) if edge.label == "HAS_ENTITY"}
        for entity, (_, path) in list(entities.items()):
            for edge in graph._outgoing.get(entity, []) + graph._incoming.get(entity, []):
                if (edge.label not in RELATIONS or not edge.properties.get("source_node_id")
                        or edge.properties.get("polarity") == "negated"):
                    continue
                other = edge.target_id if edge.source_id == entity else edge.source_id
                if other not in graph._chunk_ids and other not in entities:
                    entities[other] = (RELATED_WEIGHT, path + [{
                        "source": edge.source_id, "relation": edge.label, "target": edge.target_id,
                        "evidence": edge.properties.get("evidence", ""), "semantic_status": "requires_review"}])
        for entity, (factor, path) in entities.items():
            sources = mentioned_by(entity)
            if not sources:
                continue
            gain = factor * math.log(1 + total / len(sources)) / (rank + 1)
            for chunk in sources:
                if chunk in seed_set:
                    continue
                scores[chunk] += gain
                if len(paths[chunk]) < 20:
                    paths[chunk].extend(path + [{"source": chunk, "relation": "HAS_ENTITY", "target": entity,
                                                 "semantic_status": "mention_only"}])
    ordered = sorted(scores, key=lambda chunk: (-scores[chunk], chunk))[:limit]
    return [(chunk, scores[chunk], paths[chunk]) for chunk in ordered]


def document_context(graph, seeds, limit):
    """Título, notas e descrições das tabelas das sementes, depois o trecho seguinte/anterior.

    Linhas irmãs da mesma tabela não entram: a tabela só é ponte para seu contexto literal.
    """
    seed_set, found = set(seeds), {}
    priority = {label: position for position, label in enumerate(DOCUMENT_RELATIONS + ("NEXT_CHUNK",))}
    for rank, seed in enumerate(seeds):
        tables = {edge.source_id for edge in graph._incoming.get(seed, ())
                  if edge.label in ("REPRESENTADA_EM",) + DOCUMENT_RELATIONS and edge.source_id not in graph._chunk_ids}
        for table in sorted(tables):
            for edge in graph._outgoing.get(table, ()):
                if edge.label in DOCUMENT_RELATIONS and edge.target_id not in seed_set:
                    found.setdefault(edge.target_id, ((priority[edge.label], rank), [
                        {"source": table, "relation": "REPRESENTADA_EM", "target": seed},
                        {"source": table, "relation": edge.label, "target": edge.target_id,
                         "method": edge.properties.get("method", "document_structure"),
                         "semantic_status": edge.properties.get("semantic_status", "documentary_link")}]))
        for edge in graph._outgoing.get(seed, []) + graph._incoming.get(seed, []):
            if edge.label != "NEXT_CHUNK":
                continue
            other = edge.target_id if edge.source_id == seed else edge.source_id
            if other in graph._chunk_ids and other not in seed_set:
                found.setdefault(other, ((priority["NEXT_CHUNK"], rank), [
                    {"source": edge.source_id, "relation": "NEXT_CHUNK", "target": edge.target_id,
                     "method": "document_structure", "semantic_status": "documentary_link"}]))
    ordered = sorted((key for key in found if key in graph._chunk_ids), key=lambda key: (found[key][0], key))
    return [(key, found[key][1]) for key in ordered[:limit]]


def accept_extras(question, initial, candidates, reranker, max_per_table, limit=EXTRA_LIMIT):
    """Reordena candidatos pelo reranker e aceita os que superam o limiar da pergunta.

    Sem reranker (testes), mantém a ordem do grafo e só aplica os limites.
    Devolve os aceitos e um diagnóstico serializável.
    """
    threshold, scored = None, list(candidates)
    if reranker is not None and candidates:
        values = [float(v) for v in reranker.score(question, [item.node.text for item in initial + candidates])]
        initial_scores, extra_scores = values[:len(initial)], values[len(initial):]
        threshold = max(SCORE_FLOOR, SCORE_RATIO * min(initial_scores)) if initial_scores else SCORE_FLOOR
        for item, value in zip(candidates, extra_scores):
            item.score = value
        scored = [item for _, item in sorted(zip(extra_scores, candidates), key=lambda pair: -pair[0])
                  if item.score >= threshold]
    per_table = defaultdict(int)
    for item in initial:
        if item.metadata.get("type") == "table" and item.metadata.get("table_key"):
            per_table[item.metadata["table_key"]] += 1
    accepted = []
    for item in scored:
        table = item.metadata.get("table_key") if item.metadata.get("type") == "table" else None
        if table is not None and max_per_table > 0:
            if per_table[table] >= max_per_table:
                continue
            per_table[table] += 1
        accepted.append(item)
        if len(accepted) == limit:
            break
    diagnostics = {"threshold": threshold, "candidates": len(candidates),
                   "accepted": [{"node_id": item.node_id, "score": item.score,
                                 "origin": item.metadata.get("graph_v2_origin")} for item in accepted]}
    return accepted, diagnostics
