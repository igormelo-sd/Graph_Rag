"""Embeddings Ollama locais, com cache persistente e sem truncar entradas."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, ProxyHandler, build_opener

from llama_index.core.base.embeddings.base import BaseEmbedding


PROFILE = "embeddinggemma-search-v1-segments-2000-weighted"


def ollama_request(base_url, path, payload=None, timeout=180):
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("RAG_OLLAMA_EMBED_URL deve apontar para o Ollama local.")
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(base_url.rstrip("/") + path, data=data,
                      headers={"Content-Type": "application/json"})
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("Ollama local indisponível ou demorou demais; verifique o serviço.") from exc


def resolve_model_digest(base_url, model):
    models = ollama_request(base_url, "/api/tags").get("models", [])
    name = model if ":" in model else model + ":latest"
    for entry in models:
        if entry.get("name") == name or entry.get("model") == name:
            return entry["digest"]
    raise RuntimeError(f"Modelo '{model}' ausente no Ollama. Baixe-o com ollama pull {model}.")


def normalized(vector):
    if not vector or any(not isinstance(v, (float, int)) or not math.isfinite(v) for v in vector):
        raise RuntimeError("Ollama retornou vetor inválido.")
    norm = math.sqrt(sum(v * v for v in vector))
    if not norm:
        raise RuntimeError("Ollama retornou vetor nulo.")
    return [v / norm for v in vector]


class CachedOllamaEmbedding(BaseEmbedding):
    base_url: str = "http://127.0.0.1:11434"
    model_digest: str
    cache_path: str
    context_length: int = 2048

    def _key(self, text, query):
        identity = [PROFILE, self.model_name, self.model_digest, self.context_length, query, text]
        return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode("utf-8")).hexdigest()

    def _request_vectors(self, texts, query):
        prefix = "task: search result | query: " if query else "title: none | text: "
        result = ollama_request(self.base_url, "/api/embed", {
            "model": self.model_name,
            "input": [prefix + text for text in texts],
            "truncate": False,
            "keep_alive": "30m",
            "options": {"num_ctx": self.context_length},
        })
        vectors = result.get("embeddings", [])
        if len(vectors) != len(texts):
            raise RuntimeError("Ollama retornou quantidade incorreta de embeddings.")
        vectors = [normalized(v) for v in vectors]
        if len({len(v) for v in vectors}) > 1:
            raise RuntimeError("Ollama retornou dimensões inconsistentes.")
        return vectors

    def _encode_segment(self, text, query):
        try:
            return self._request_vectors([text], query)[0]
        except RuntimeError as exc:
            message = str(exc).lower()
            if "context length" not in message and "input length" not in message:
                raise
            if len(text) < 2:
                raise
            mid = len(text) // 2
            return self._pool([self._encode_segment(text[:mid], query),
                               self._encode_segment(text[mid:], query)],
                              [mid, len(text) - mid])

    @staticmethod
    def _pool(vectors, weights):
        if len({len(v) for v in vectors}) != 1:
            raise RuntimeError("Dimensões inconsistentes nos segmentos.")
        return normalized([sum(v[d] * w for v, w in zip(vectors, weights))
                           for d in range(len(vectors[0]))])

    def _encode_missing(self, texts, query):
        segments = [text[start:start + 2000] for text in texts
                    for start in range(0, max(len(text), 1), 2000)]
        vectors = []
        for start in range(0, len(segments), self.embed_batch_size):
            batch = segments[start:start + self.embed_batch_size]
            try:
                vectors.extend(self._request_vectors(batch, query))
            except RuntimeError as exc:
                message = str(exc).lower()
                if "context length" not in message and "input length" not in message:
                    raise
                vectors.extend(self._encode_segment(t, query) for t in batch)
        pooled = []
        offset = 0
        for text in texts:
            count = max(1, (len(text) + 1999) // 2000)
            weights = [max(1, len(text[i:i + 2000])) for i in range(0, max(len(text), 1), 2000)]
            pooled.append(self._pool(vectors[offset:offset + count], weights))
            offset += count
        return pooled

    def _cached(self, texts, query=False):
        Path(self.cache_path).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.cache_path, timeout=30)) as cache:
            cache.execute("CREATE TABLE IF NOT EXISTS embeddings (key TEXT PRIMARY KEY, vector TEXT NOT NULL)")
            keys = [self._key(text, query) for text in texts]
            known = {}
            missing = {}
            for key, text in zip(keys, texts):
                row = cache.execute("SELECT vector FROM embeddings WHERE key = ?", (key,)).fetchone()
                if row:
                    known[key] = normalized(json.loads(row[0]))
                else:
                    missing.setdefault(key, text)
            # Cada lote de inferência é durável mesmo se a escrita no Chroma falhar.
            items = list(missing.items())
            for start in range(0, len(items), self.embed_batch_size):
                batch = items[start:start + self.embed_batch_size]
                vectors = self._encode_missing([text for _, text in batch], query)
                for (key, _), vector in zip(batch, vectors):
                    cache.execute("INSERT OR REPLACE INTO embeddings VALUES (?, ?)", (key, json.dumps(vector)))
                    known[key] = vector
                cache.commit()
            result = [known[key] for key in keys]
            if len({len(v) for v in result}) > 1:
                raise RuntimeError("Cache de embeddings tem dimensões inconsistentes.")
            return result

    def _get_text_embedding(self, text):
        return self._cached([text])[0]

    def _get_text_embeddings(self, texts):
        return self._cached(texts)

    def _get_query_embedding(self, query):
        return self._cached([query], query=True)[0]

    async def _aget_query_embedding(self, query):
        return await asyncio.to_thread(self._get_query_embedding, query)

    async def _aget_text_embedding(self, text):
        return await asyncio.to_thread(self._get_text_embedding, text)
