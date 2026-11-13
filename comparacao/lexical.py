"""Expansão lexical por tabela e por documento, sem grafo: o controle do GraphRAG.

Reproduz o gerador de candidatos que mais contribuiu no GraphRAG (`label_candidates`): a partir
dos trechos iniciais, olha as linhas da mesma tabela e os trechos do mesmo documento e escolhe os que
repetem termos raros da pergunta (raridade dentro do próprio escopo, log N/df). A diferença é que aqui
os escopos vêm dos metadados dos trechos (`table_key`, `source_file`), e não de arestas de um grafo.
Se esta variante igualar o GraphRAG, o ganho do grafo era busca lexical por escopo.
"""
import math
import re
from collections import defaultdict
from copy import deepcopy

from llama_index.core.schema import NodeWithScore

_TERM = re.compile(r"\d+(?:[.,/-]\d+)*[a-z]?|[a-z]{3,}")
_STOPWORDS = frozenset(
    "com das dos entre foi nas nos para pela pelas pelo pelos por qual quais que sua suas seu seus uma "
    "como quanto quanta quantos quantas onde quando sobre segundo valor".split())


def terms(text):
    """Termos sem acento; números e anos ficam inteiros (mesma regra do GraphRAG)."""
    from domain_ontology import fold
    return {term for term in _TERM.findall(fold(str(text))) if term not in _STOPWORDS}


class LexicalExpander:
    def __init__(self, nodes):
        self.nodes = {node.node_id: node for node in nodes}
        self.by_table, self.by_document = defaultdict(list), defaultdict(list)
        self.table_of, self.document_of = {}, {}
        for node in nodes:
            metadata = node.metadata
            if metadata.get("type") == "table" and metadata.get("table_key"):
                self.by_table[metadata["table_key"]].append(node.node_id)
                self.table_of[node.node_id] = metadata["table_key"]
            if metadata.get("source_file"):
                self.by_document[metadata["source_file"]].append(node.node_id)
                self.document_of[node.node_id] = metadata["source_file"]
        self._terms = {}

    def _row_terms(self, identity):
        if identity not in self._terms:
            self._terms[identity] = terms(self.nodes[identity].text)
        return self._terms[identity]

    def _scopes(self, seed):
        if seed in self.table_of:
            yield ("table", self.table_of[seed]), self.by_table[self.table_of[seed]]
        if seed in self.document_of:
            yield ("document", self.document_of[seed]), self.by_document[self.document_of[seed]]

    def candidates(self, seeds, question, limit=8):
        """Trechos do escopo das sementes com termos raros da pergunta, do mais ao menos relevante."""
        from domain_ontology import filter_candidates
        wanted = terms(question)
        if not wanted:
            return []
        identities = list(dict.fromkeys(str(node.node_id) for node in seeds))
        original = set(identities)
        best, scopes_seen = {}, set()
        for rank, seed in enumerate(identities):
            for scope, members in self._scopes(seed):
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
                    matched = [term for term in self._row_terms(member) & wanted if weight[term] > 0]
                    score = sum(weight[term] for term in matched) / (rank + 1)
                    if score > best.get(member, (0.0,))[0]:
                        best[member] = (score, rank)
        if not best:
            return []
        top = max(score for score, _ in best.values())
        ordered = sorted(best, key=lambda row: (-best[row][0], best[row][1], row))[:limit * 4]
        found = [NodeWithScore(node=deepcopy(self.nodes[identity]), score=round(0.4 * best[identity][0] / top, 4))
                 for identity in ordered]
        return filter_candidates(found, question)[:limit]
