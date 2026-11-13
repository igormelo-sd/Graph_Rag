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
import json
from collections import defaultdict

POOL = 16           # candidatos por origem levados ao reranker
EXTRA_LIMIT = 6     # extras aceitos depois do reranker
SCORE_RATIO = 0.25  # fração do menor escore inicial exigida dos extras
SCORE_FLOOR = 0.02  # escore mínimo absoluto, para perguntas com iniciais fracos


LINKED_RELATIONS = ("DICIONARIO_DE", "TEM_NOTA")  # vínculos documentais explícitos
LINKED_CAP = 2  # contexto vinculado aceito sem passar pelo limiar
GAP_CAP = 2     # evidências de recortes da pergunta sem apoio, também sem o limiar


def is_linked(item):
    """Candidato documental alcançado por dicionário ou nota da tabela de uma semente."""
    if item.metadata.get("graph_origin") != "documentary":
        return False
    try:
        steps = json.loads(item.metadata.get("graph_paths") or "[]")
    except (TypeError, ValueError):
        return False
    return any(step.get("relation") in LINKED_RELATIONS for step in steps if isinstance(step, dict))


def accept_extras(question, initial, candidates, reranker, max_per_table):
    """Reordena candidatos pelo reranker e aceita os que superam o limiar da pergunta.

    O dicionário e as notas ligados por aresta explícita à tabela de uma semente (até
    `LINKED_CAP`) entram sem o limiar: pontuados isoladamente, definem a série mas não
    parecem responder à pergunta. Sem reranker (testes), mantém a ordem do grafo e só
    aplica os limites. Devolve os aceitos e um diagnóstico serializável.
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
    # Vinculados (dicionário e notas) primeiro, sem limiar, e depois os aprovados pelo reranker.
    linked = [item for item in candidates if is_linked(item)][:LINKED_CAP]
    gaps = [item for item in candidates if item.metadata.get("graph_origin") == "gap"][:GAP_CAP]
    linked_ids = {item.node_id for item in linked + gaps}
    scored = linked + gaps + [item for item in scored if item.node_id not in linked_ids]
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
                                 "origin": item.metadata.get("graph_origin"),
                                 "linked": item.node_id in linked_ids} for item in accepted]}
    return accepted, diagnostics
