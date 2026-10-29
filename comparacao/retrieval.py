"""Ranking inicial comum às duas versões: vetorial, BM25, fusão RRF, reranking e diversificação.

Tudo aqui acontece antes de `strategy.retrieve()`, então RAG simples e GraphRAG
recebem exatamente os mesmos trechos iniciais.
"""
import re
import unicodedata

STOPWORDS = frozenset(
    "a ao aos as com da das de do dos e em entre foi na nas no nos o os ou para pela pelas pelo pelos "
    "por qual quais que se sua suas seu seus um uma".split())
TOKEN = re.compile(r"\d+(?:[.,/-]\d+)*|[a-z]+")


def tokenize(text):
    """Minúsculas sem acentos; códigos e números como 47.32-6 ou 3.277,8 ficam inteiros."""
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    return [token for token in TOKEN.findall(plain) if token not in STOPWORDS]


class BM25Index:
    def __init__(self, chunks):
        from rank_bm25 import BM25Okapi
        self.chunks = chunks
        self.bm25 = BM25Okapi([tokenize(chunk["text"]) or ["_"] for chunk in chunks])

    def search(self, question, limit):
        scores = self.bm25.get_scores(tokenize(question))
        order = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)[:limit]
        return [{**self.chunks[index], "score": float(scores[index])} for index in order if scores[index] > 0]


def node_id(item):
    return item["metadata"]["node_id"]


def rrf_fuse(rankings, k=60):
    """Reciprocal Rank Fusion; guarda a posição de cada trecho em cada lista."""
    fused = {}
    for name, ranking in rankings.items():
        for position, item in enumerate(ranking, 1):
            entry = fused.setdefault(node_id(item), {**item, "score": 0.0, "ranks": {}})
            entry["score"] += 1.0 / (k + position)
            entry["ranks"][name] = position
    return sorted(fused.values(), key=lambda item: item["score"], reverse=True)


def diversify(ranking, limit, max_per_table):
    """Mantém a ordem e limita trechos da mesma tabela; 0 desativa o limite."""
    if max_per_table <= 0:
        return ranking[:limit]
    selected, per_table = [], {}
    for item in ranking:
        table = item["metadata"].get("table_key") if item["metadata"].get("type") == "table" else None
        if table is not None:
            if per_table.get(table, 0) >= max_per_table:
                continue
            per_table[table] = per_table.get(table, 0) + 1
        selected.append(item)
        if len(selected) == limit:
            break
    return selected


class Reranker:
    """Cross-encoder local que reordena os primeiros candidatos pela relevância à pergunta."""

    def __init__(self, model_name):
        from sentence_transformers import CrossEncoder
        self.model = CrossEncoder(model_name, device="cpu", max_length=512)

    def rerank(self, question, candidates):
        scores = self.model.predict([(question, item["text"]) for item in candidates], batch_size=8)
        order = sorted(range(len(candidates)), key=lambda index: float(scores[index]), reverse=True)
        return [{**candidates[index], "score": float(scores[index]),
                 "ranks": {**candidates[index]["ranks"], "rerank": position}}
                for position, index in enumerate(order, 1)]

    def score(self, question, texts):
        """Escores na mesma escala do reranking inicial, na ordem recebida."""
        return [float(value) for value in self.model.predict([(question, text) for text in texts], batch_size=8)]


def initial_ranking(question, rag, payload, settings, bm25=None, reranker=None):
    """Trechos iniciais conforme o perfil: `dense` ou `hybrid`, com reranking opcional."""
    pool = max(settings["candidate_pool"], settings["top_k"])
    dense = rag.search(question, pool, payload)
    if settings["retrieval_mode"] == "hybrid":
        ranking = rrf_fuse({"vetorial": dense, "bm25": bm25.search(question, pool)}, settings["rrf_k"])
    else:
        ranking = [{**item, "ranks": {"vetorial": position}} for position, item in enumerate(dense, 1)]
    if reranker is not None:
        head = settings["rerank_pool"]
        ranking = reranker.rerank(question, ranking[:head]) + ranking[head:]
    return diversify(ranking, settings["top_k"], settings["max_per_table"])
