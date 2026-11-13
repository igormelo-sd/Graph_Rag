"""Ranking inicial comum às duas versões: vetorial, BM25, fusão RRF, reranking e diversificação.

Tudo aqui acontece antes de `strategy.retrieve()`, então RAG simples e GraphRAG
recebem exatamente os mesmos trechos iniciais.
"""
import re
import unicodedata
from pathlib import Path

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
    def __init__(self, chunks, contextual=False):
        from comparacao.common import search_text
        from rank_bm25 import BM25Okapi
        self.chunks = chunks
        self.bm25 = BM25Okapi([tokenize(search_text(chunk["text"], chunk.get("metadata"), contextual)) or ["_"]
                               for chunk in chunks])

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


def ontology_filter(question, ranking):
    """Remove candidatos em conflito explícito com o recorte da pergunta.

    Mesma regra da ontologia de domínio usada pelo GraphRAG (`filter_candidates`),
    mas aplicada ao ranking comum: indicador, território, período, unidade,
    escala ou setor incompatíveis saem; dados incompletos permanecem. Não usa grafo.
    Exige que `graph_modules()` já tenha sido chamado.
    """
    from types import SimpleNamespace
    from domain_ontology import filter_candidates
    wrapped = [SimpleNamespace(text=item["text"], get_content=lambda text=item["text"]: text, item=item)
               for item in ranking]
    return [node.item for node in filter_candidates(wrapped, question)]


DICTIONARY_PREFIXES = ("dicvar_", "dic_variaveis_")
DICTIONARY_TOP = 3
DEFINITIONAL = re.compile(
    r"\b(defin\w*|signific\w*|dicionario|variaveis|variavel|conceit\w*|hierarq\w*|nomenclatura|classific\w*|regionaliza\w*)\b")


def is_definitional(question):
    """Pergunta sobre definição, variável ou estrutura de uma classificação (intenção, não conteúdo do corpus)."""
    plain = "".join(char for char in unicodedata.normalize("NFKD", question.lower()) if not unicodedata.combining(char))
    return bool(DEFINITIONAL.search(plain))


def dictionary_positions(payload):
    """Posições, no índice, dos trechos de dicionários de variáveis (`dicvar_*`, `dic_variaveis_*`)."""
    if "_dictionary" not in payload:
        payload["_dictionary"] = [index for index, chunk in enumerate(payload["chunks"])
                                  if Path(str(chunk.get("source", ""))).stem.lower().startswith(DICTIONARY_PREFIXES)]
    return payload["_dictionary"]


EXACT_METHODS = ("structured_exact", "structured_catalogue")
EXACT_CAP = 2  # linhas exatas (código, célula, município) que passam à frente do ranking


def initial_ranking(question, rag, payload, settings, bm25=None, reranker=None, extra=0, structured=None):
    """Trechos iniciais conforme o perfil: `dense` ou `hybrid`, com reranking opcional.

    `extra` acrescenta, depois dos `top_k` primeiros, os próximos trechos do mesmo
    ranking (reserva). Como a diversificação é gulosa, os `top_k` primeiros não mudam.

    `structured(question)` devolve itens da busca literal no corpus tabular inteiro. Só os
    exatos (código, célula, município ou catálogo identificados) entram: passam à frente do
    ranking, no máximo `EXACT_CAP`. As linhas apenas lexicais (sobreposição de palavras) são
    descartadas: na rodada v4_dev_20261112_r2, 25 delas chegaram aos contextos e só 1 ajudou,
    enquanto desalojavam trechos úteis (D001, D016). Igual para todas as versões.
    """
    pool = max(settings["candidate_pool"], settings["top_k"])
    dense = rag.search(question, pool, payload)
    found = structured(question) if structured is not None else []
    exact = [item for item in found if item["metadata"].get("retrieval_method") in EXACT_METHODS][:EXACT_CAP]
    # Perguntas de definição vão também aos dicionários de variáveis, que são pequenos e quase nunca
    # aparecem entre os candidatos gerais (D014, D016). Igual para todas as versões.
    routed = []
    if settings.get("dictionary_routing") and payload is not None and is_definitional(question):
        routed = rag.search(question, DICTIONARY_TOP, payload, subset=dictionary_positions(payload))
    if settings["retrieval_mode"] == "hybrid":
        rankings = {"vetorial": dense, "bm25": bm25.search(question, pool)}
        if routed:
            rankings["dicionario"] = routed
        ranking = rrf_fuse(rankings, settings["rrf_k"])
    else:
        ranking = [{**item, "ranks": {"vetorial": position}} for position, item in enumerate(dense, 1)]
        present = {node_id(item) for item in ranking}
        ranking += [{**item, "ranks": {"dicionario": position}}
                    for position, item in enumerate(routed, 1) if node_id(item) not in present]
    if settings.get("ontology_filter"):
        ranking = ontology_filter(question, ranking)
    if reranker is not None:
        head = settings["rerank_pool"]
        ranking = reranker.rerank(question, ranking[:head]) + ranking[head:]
    if exact:
        taken = {node_id(item) for item in exact}
        ranking = [{**item, "ranks": {"estruturada_exata": position}} for position, item in enumerate(exact, 1)] \
            + [item for item in ranking if node_id(item) not in taken]
    return diversify(ranking, settings["top_k"] + extra, settings["max_per_table"])
