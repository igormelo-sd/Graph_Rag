"""Resolve módulos locais sem depender da estrutura do antigo monorepo.

Por padrão testa `graph_rag/src`. Com `RAG_TEST_IMPL=simple_rag`, a mesma suíte roda contra
`simple_rag/src`: os testes que exigem módulos de grafo são pulados e os demais cobrem os
módulos que as duas pastas compartilham.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTATION = ROOT.parent / os.environ.get("RAG_TEST_IMPL", ROOT.name)
for directory in (IMPLEMENTATION.parent, IMPLEMENTATION, IMPLEMENTATION / "src"):
    sys.path.insert(0, str(directory))

NEEDS_GRAPH = IMPLEMENTATION.name == "graph_rag"
# Arquivos inteiros que dependem de módulos de grafo ou de graph_rag/scripts.
GRAPH_ONLY_FILES = {"test_graph_paths.py", "test_graph_patterns.py", "test_graph_relevance.py",
                    "test_index_artifact.py", "test_statistical_graph.py", "test_dictionary_links.py",
                    "test_gap_planning.py"}
# Testes de grafo dentro de arquivos que também cobrem módulos compartilhados.
GRAPH_ONLY_TESTS = {
    "test_oversized_community_summary_is_rewritten_not_truncated",
    "test_persistently_oversized_summary_is_rejected",
    "test_graph_cache_restores_concrete_nodes_and_relations",
    "test_valid_graph_cache_is_not_rebuilt_or_rewritten",
    "test_graph_save_failure_keeps_previous_cache",
    "test_entidade_canonica_usa_tipo_e_periodo_do_cadastro",
    "test_cache_de_extracao_evita_nova_chamada_e_revalida",
    "test_cache_de_extracao_ignora_linha_parcial",
    "test_relacao_negada_e_preservada_sem_virar_afirmacao",
    "test_cobertura_ordena_sem_excluir_observacoes",
    "test_comunidades_ignoram_relacao_negada",
    "test_relatorio_de_auditoria_agrupa_rejeicoes_e_polaridade",
    "test_exportacao_skos_descreve_relacoes_sem_axiomas_de_dominio",
}


def pytest_ignore_collect(collection_path, config):
    return not NEEDS_GRAPH and collection_path.name in GRAPH_ONLY_FILES


def pytest_collection_modifyitems(config, items):
    if NEEDS_GRAPH:
        return
    skip = pytest.mark.skip(reason="requer módulos de grafo (ausentes em simple_rag)")
    for item in items:
        if item.name.split("[")[0] in GRAPH_ONLY_TESTS:
            item.add_marker(skip)
