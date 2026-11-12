"""Validação, normalização e ranking dos vetores de recuperação."""
import math


def normalize(vector: list[float]) -> list[float]:
    if not vector or any(not math.isfinite(x) for x in vector):
        raise ValueError("Vetor vazio ou com valores inválidos.")
    norm = math.sqrt(sum(x * x for x in vector))
    if not math.isfinite(norm) or norm == 0:
        raise ValueError("Vetor sem norma válida.")
    return [x / norm for x in vector]


def rank_by_cosine(query: list[float], chunks: list[dict], vectors: list[list[float]],
                   top_k: int) -> list[dict]:
    """Busca exata; espera vetores já normalizados, então o produto interno é o cosseno."""
    if len(query) != len(vectors[0]):
        raise ValueError("Dimensão dos embeddings mudou. Execute indexar novamente.")
    results = [{**chunk, "score": sum(a * b for a, b in zip(query, vector))}
               for chunk, vector in zip(chunks, vectors)]
    return sorted(results, key=lambda item: item["score"], reverse=True)[:top_k]
