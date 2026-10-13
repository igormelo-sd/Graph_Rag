"""RAG tradicional: documentos -> trechos -> vetores -> busca -> resposta."""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from comparacao.common import apply_profile, embedding_model, llm_model, pack_results, answer_prompt
from rag_simples.documents import SUPPORTED, Chunk, split_text, read_documents
from rag_simples.vectors import normalize
from rag_app.storage import write_json


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

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._embedder is None:
            self._embedder = embedding_model(self.embedding_model)
        return [normalize(vector) for vector in self._embedder.get_text_embedding_batch(texts)]

    def embed_query(self, question):
        if self._embedder is None:
            self._embedder = embedding_model(self.embedding_model)
        return normalize(self._embedder.get_query_embedding(question))

    def index(self, directory: Path, size: int = 1024, overlap: int = 200) -> int:
        # Valida mesmo que a pasta esteja vazia.
        split_text("", size, overlap)
        chunks = read_documents(directory, size, overlap)
        return self.index_chunks(chunks, size, overlap)

    def index_chunks(self, chunks, size=1024, overlap=200, experiment=None):
        vectors = self.embed([chunk.text for chunk in chunks])
        if len(vectors) != len(chunks) or len({len(v) for v in vectors}) != 1:
            raise ValueError("Embeddings incompatíveis com os trechos dos documentos.")
        payload = {
            "version": 2,
            "embedding_backend": "huggingface-local",
            "embedding_model": self.embedding_model,
            "chunk_size": size,
            "chunk_overlap": overlap,
            "chunks": [asdict(chunk) for chunk in chunks],
            "vectors": [normalize(v) for v in vectors],
            "experiment": experiment,
        }
        write_json(self.index_path, payload)
        return len(chunks)

    def load_index(self) -> dict:
        if not self.index_path.is_file():
            raise ValueError("Índice não encontrado. Execute primeiro o comando indexar.")
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
            model = payload["embedding_model"]
            chunks, vectors = payload["chunks"], payload["vectors"]
            if (payload["version"] != 2 or payload.get("embedding_backend") != "huggingface-local"
                    or not chunks or len(chunks) != len(vectors)
                    or len({len(v) for v in vectors}) != 1):
                raise ValueError("Estrutura inválida.")
            for chunk in chunks:
                Chunk(**chunk)
            payload["vectors"] = [normalize(v) for v in vectors]
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError("Índice inválido. Execute indexar novamente.") from exc
        if model != self.embedding_model:
            raise ValueError("O modelo de embeddings mudou. Execute indexar novamente.")
        return payload

    def search(self, question: str, top_k: int = 5) -> list[dict]:
        if not question.strip():
            raise ValueError("A pergunta não pode estar vazia.")
        if top_k <= 0:
            raise ValueError("top-k deve ser maior que zero.")
        payload = self.load_index()
        query = normalize(self.embed_query(question))
        if len(query) != len(payload["vectors"][0]):
            raise ValueError("Dimensão dos embeddings mudou. Execute indexar novamente.")
        results = []
        for chunk, vector in zip(payload["chunks"], payload["vectors"]):
            score = sum(a * b for a, b in zip(query, vector))
            results.append({**chunk, "score": score})
        return sorted(results, key=lambda item: item["score"], reverse=True)[:top_k]

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


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    apply_profile()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--indice", type=Path, default=ROOT / "indice" / "index.json")
    commands = parser.add_subparsers(dest="command", required=True)
    index = commands.add_parser("indexar", help="Cria ou substitui o índice completo.")
    index.add_argument("--documentos", type=Path, default=Path(os.environ["RAG_DATA_DIR"]))
    index.add_argument("--tamanho", type=int, default=int(os.environ["RAG_CHUNK_SIZE"]))
    index.add_argument("--sobreposicao", type=int, default=int(os.environ["RAG_CHUNK_OVERLAP"]))
    query = commands.add_parser("perguntar", help="Busca trechos e responde à pergunta.")
    query.add_argument("pergunta")
    query.add_argument("--top-k", type=int, default=int(os.environ["RAG_RETRIEVAL_TOP_K"]))
    query.add_argument("--somente-busca", action="store_true", help="Exibe trechos sem chamar o LLM.")
    comparison = commands.add_parser("comparar", help="Usa o corpus e o perfil experimental compartilhados.")
    comparison.add_argument("pergunta")
    args = parser.parse_args()
    if args.command == "comparar":
        load_dotenv(ROOT.parent / "comparacao" / ".env", override=True)
        from comparacao.run import compare
        print(json.dumps(compare(args.pergunta, "rag_simples"), ensure_ascii=False, indent=2))
        return
    rag = SimpleRAG(args.indice, os.environ["RAG_EMBED_MODEL"], os.environ["RAG_LLM_MODEL"])
    try:
        if args.command == "indexar":
            count = rag.index(args.documentos, args.tamanho, args.sobreposicao)
            print(f"Índice criado com {count} trechos em {args.indice}.")
            return
        results = rag.search(args.pergunta, args.top_k)
        if not args.somente_busca:
            print(rag.answer(args.pergunta, results))
        print("\nFontes recuperadas (similaridade não é uma probabilidade):")
        for i, item in enumerate(results, start=1):
            page = f", página {item['page']}" if item["page"] else ""
            print(f"[{i}] {item['source']}{page}, trecho {item['number']} — {item['score']:.3f}")
            if args.somente_busca:
                print(item["text"] + "\n")
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Erro: {exc}\n")


if __name__ == "__main__":
    main()
