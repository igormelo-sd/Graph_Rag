"""Leitura e validação do perfil experimental, sem alterar o ambiente."""
import json
import math
from pathlib import Path

INTEGER_LIMITS = {
    "chunk_size": (256, 8192), "parent_size": (256, 16000),
    "chunk_overlap": (0, 8191), "top_k": (1, 200),
    "context_tokens": (1000, 100000), "max_output_tokens": (1, None),
    "embedding_batch_size": (1, 128), "embedding_max_length": (512, 8192),
    "entity_context_limit": (1, 40), "entity_context_depth": (0, 2),
    "graph_context_limit": (1, 30), "graph_context_depth": (1, 3),
    "community_summary_chars": (200, 6000),
}


def load_profile(path: Path) -> dict:
    settings = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(settings, dict):
        raise ValueError("O perfil deve ser um objeto JSON.")
    if type(settings.get("version")) is not int or settings["version"] != 1:
        raise ValueError("Versão desconhecida do perfil de comparação.")
    for key, (minimum, maximum) in INTEGER_LIMITS.items():
        value = settings.get(key)
        if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
            raise ValueError(f"Configuração inválida: {key}.")
    for key in ("corpus", "llm_model", "embedding_model"):
        value = settings.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Configuração inválida: {key}.")
    for key, allowed in (("provider", ("openai", "openrouter", "ollama")),
                         ("embedding_device", ("cpu", "cuda"))):
        if settings.get(key) not in allowed:
            raise ValueError(f"Configuração inválida: {key}.")
    temperature = settings.get("temperature")
    if type(temperature) not in (int, float) or not math.isfinite(temperature) or not 0 <= temperature <= 2:
        raise ValueError("Configuração inválida: temperature.")
    if settings["chunk_overlap"] >= settings["chunk_size"]:
        raise ValueError("Sobreposição inválida.")
    if settings["parent_size"] < settings["chunk_size"]:
        raise ValueError("parent_size deve ser maior ou igual a chunk_size.")
    return settings
