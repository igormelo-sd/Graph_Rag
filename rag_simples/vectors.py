"""Validação e normalização dos vetores de recuperação."""
import math

def normalize(vector: list[float]) -> list[float]:
    if not vector or any(not math.isfinite(x) for x in vector):
        raise ValueError("Vetor vazio ou com valores inválidos.")
    norm = math.sqrt(sum(x * x for x in vector))
    if not math.isfinite(norm) or norm == 0:
        raise ValueError("Vetor sem norma válida.")
    return [x / norm for x in vector]


