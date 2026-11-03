"""Seleção dos candidatos do grafo do GraphRAG pelo mesmo reranker do ranking inicial.

O grafo propõe candidatos (entidades compartilhadas, trechos da mesma tabela ou
documento com rótulos raros da pergunta, contexto documental e busca guiada
pela pergunta); o reranker decide. Só entram
candidatos com escore de pelo menos SCORE_RATIO vezes o menor escore inicial da
pergunta, no máximo EXTRA_LIMIT, respeitando o limite por tabela do perfil.
Assim o grafo disputa espaço pela relevância, e o contexto não cresce com
vizinhos que ninguém avaliou. Os parâmetros ficam aqui, e não em `config.json`,
porque descrevem a estratégia do GraphRAG, não o perfil comum às versões.
"""
from collections import defaultdict

POOL = 16           # candidatos por origem levados ao reranker
EXTRA_LIMIT = 6     # extras aceitos depois do reranker
SCORE_RATIO = 0.25  # fração do menor escore inicial exigida dos extras
SCORE_FLOOR = 0.02  # escore mínimo absoluto, para perguntas com iniciais fracos


def accept_extras(question, initial, candidates, reranker, max_per_table):
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
        if len(accepted) == EXTRA_LIMIT:
            break
    origins = defaultdict(int)
    for item in candidates:
        origins[item.metadata.get("graph_origin", "?")] += 1
    diagnostics = {"threshold": threshold, "candidates": dict(origins),
                   "accepted": [{"node_id": item.node_id, "score": item.score,
                                 "origin": item.metadata.get("graph_origin")} for item in accepted]}
    return accepted, diagnostics
