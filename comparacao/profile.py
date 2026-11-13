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
    "candidate_pool": (1, 1000), "rrf_k": (1, 1000), "max_per_table": (0, 200),
    "rerank_pool": (1, 200), "min_text_chars": (0, 2000), "small_table_rows": (0, 200),
    "small_table_chars": (500, 20000), "baseline_extra_slots": (0, 30),
}


def load_profile(path: Path) -> dict:
    settings = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(settings, dict):
        raise ValueError("O perfil deve ser um objeto JSON.")
    if type(settings.get("version")) is not int or settings["version"] != 1:
        raise ValueError("Versão desconhecida do perfil de comparação.")
    # Perfis anteriores não tinham estes campos: embeddings locais e só busca vetorial.
    settings.setdefault("embedding_provider", "huggingface")
    settings.setdefault("retrieval_mode", "dense")
    settings.setdefault("candidate_pool", settings.get("top_k"))
    settings.setdefault("rrf_k", 60)
    settings.setdefault("max_per_table", 0)
    settings.setdefault("reranker", "")
    settings.setdefault("rerank_pool", settings.get("top_k"))
    settings.setdefault("min_text_chars", 0)
    settings.setdefault("small_table_rows", 0)
    settings.setdefault("small_table_chars", 6000)
    # v4: vagas extras do RAG simples (próximos trechos do ranking) e filtro de ontologia comum.
    settings.setdefault("baseline_extra_slots", 0)
    settings.setdefault("ontology_filter", False)
    # Busca literal no corpus tabular inteiro (linhas além do teto de 1.000, códigos, células), comum às versões.
    settings.setdefault("structured_lookup", False)
    # Cabeçalho (documento, tabela, seção) no texto embutido e no BM25; exige reindexar.
    settings.setdefault("contextual_embedding", False)
    # Trechos de dicionários de variáveis para perguntas de definição ou estrutura.
    settings.setdefault("dictionary_routing", False)
    # Expansão do grafo guiada pelos recortes da pergunta que o contexto ainda não sustenta.
    settings.setdefault("gap_planning", False)
    # Candidatos do grafo por PageRank personalizado (NetworkX) a partir dos trechos iniciais.
    settings.setdefault("graph_ppr", False)
    for flag in ("ontology_filter", "structured_lookup", "contextual_embedding", "dictionary_routing", "gap_planning",
                 "graph_ppr"):
        if type(settings[flag]) is not bool:
            raise ValueError(f"Configuração inválida: {flag}.")
    if not isinstance(settings["reranker"], str):
        raise ValueError("Configuração inválida: reranker.")
    for key, (minimum, maximum) in INTEGER_LIMITS.items():
        value = settings.get(key)
        if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
            raise ValueError(f"Configuração inválida: {key}.")
    for key in ("corpus", "llm_model", "embedding_model"):
        value = settings.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Configuração inválida: {key}.")
    for key, allowed in (("provider", ("openai", "openrouter", "ollama")),
                         ("embedding_provider", ("huggingface", "openai")),
                         ("retrieval_mode", ("dense", "hybrid")),
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
