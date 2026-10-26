"""RAG tradicional: documentos -> trechos -> vetores -> busca -> resposta."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from comparacao.common import embedding_model, llm_model, pack_results, answer_prompt
from rag_simples.documents import SUPPORTED, Chunk, split_text, read_documents
from rag_simples.index_store import save_index, load_index
from rag_simples.vectors import normalize, rank_by_cosine

__all__ = ["SimpleRAG", "Chunk", "split_text", "main"]


class SimpleRAG:
    def __init__(self, index_path: Path, embedding_model: str, llm_model: str):
        self.index_path = Path(index_path)
        self.embedding_model = embedding_model
        self.llm_model = llm_model
        self._client = None
        self._embedder = None

    @property
    def client(self):
        if self._client is None:
            self._client = llm_model(self.llm_model)
        return self._client

    @property
    def embedder(self):
        if self._embedder is None:
            self._embedder = embedding_model(self.embedding_model)
        return self._embedder

    @embedder.setter
    def embedder(self, value):
        self._embedder = value

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [normalize(vector) for vector in self.embedder.get_text_embedding_batch(texts)]

    def embed_query(self, question: str) -> list[float]:
        return normalize(self.embedder.get_query_embedding(question))

    def index(self, directory: Path, size: int = 1024, overlap: int = 200) -> int:
        # Valida mesmo que a pasta esteja vazia.
        split_text("", size, overlap)
        chunks = read_documents(directory, size, overlap)
        return self.index_chunks(chunks, size, overlap)

    def index_chunks(self, chunks, size=1024, overlap=200, experiment=None) -> int:
        vectors = self.embed([chunk.text for chunk in chunks])
        save_index(self.index_path, chunks, vectors, embedding_model=self.embedding_model,
                   size=size, overlap=overlap, experiment=experiment)
        return len(chunks)

    def load_index(self) -> dict:
        return load_index(self.index_path, self.embedding_model)

    def search(self, question: str, top_k: int = 5, payload: dict | None = None) -> list[dict]:
        """`payload` permite reutilizar um índice já carregado e validado em lotes."""
        if not question.strip():
            raise ValueError("A pergunta não pode estar vazia.")
        if top_k <= 0:
            raise ValueError("top-k deve ser maior que zero.")
        payload = payload or self.load_index()
        # Normaliza de novo: embed_query pode ser substituído por implementações externas.
        query = normalize(self.embed_query(question))
        return rank_by_cosine(query, payload["chunks"], payload["vectors"], top_k)

    def answer(self, question: str, results: list[dict]) -> str:
        if not results:
            return "Não há trechos disponíveis para responder à pergunta."
        context, included = pack_results(results)
        if not included:
            return "Nenhum trecho cabe no orçamento de contexto."
        content = self.client.complete(answer_prompt(question, context)).text
        if not content:
            raise ValueError("O modelo não retornou uma resposta em texto.")
        return content


def main(argv=None) -> None:
    from rag_simples.cli import main as run
    run(argv)


if __name__ == "__main__":
    main()
