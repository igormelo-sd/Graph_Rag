"""Ligação determinística dicionário -> tabela-base, pela convenção de nomes do corpus."""
from llama_index.core.graph_stores import SimplePropertyGraphStore
from llama_index.core.schema import TextNode

from graph_indexing import dictionary_base_files, inject_deterministic_triplets

CORPUS = ["cnae20.csv", "dicvar_cnae20.csv", "codigos_municipios_regioes.csv", "dicvar_codigos_municipios_regioes.csv",
          "pib_municipal_2002_2020.csv", "dicvar_pib_municipal_2002_2020.csv", "base-pmc_spbrasil.csv",
          "dic_variaveis_pmc.csv", "base-pms_spbrasil.csv", "dic_variaveis_pms.csv", "pmc_202512caderno.pdf",
          "base-pim_spbrasil.csv"]


def test_dictionaries_map_to_their_unique_base_table():
    links = dictionary_base_files(CORPUS)
    assert links == {"dicvar_cnae20.csv": "cnae20.csv",
                     "dicvar_codigos_municipios_regioes.csv": "codigos_municipios_regioes.csv",
                     "dicvar_pib_municipal_2002_2020.csv": "pib_municipal_2002_2020.csv",
                     "dic_variaveis_pmc.csv": "base-pmc_spbrasil.csv",
                     "dic_variaveis_pms.csv": "base-pms_spbrasil.csv"}


def test_ambiguous_or_missing_base_creates_no_link():
    assert dictionary_base_files(["dicvar_x.csv", "x.csv", "base-x_a.csv"]) == {}      # duas bases
    assert dictionary_base_files(["dicvar_y.csv", "z.csv"]) == {}                        # nenhuma base
    assert dictionary_base_files(["dicvar_p.csv", "p_2020.pdf"]) == {}                   # PDF não é tabela-base


def table_chunk(identity, source, key):
    return TextNode(id_=identity, text=f"{source}: {identity}", metadata={
        "type": "table", "source_file": source, "page": "Planilha", "table_key": key, "chunk_id": 1})


def test_graph_links_dictionary_chunks_to_the_base_table_entity():
    store = SimplePropertyGraphStore()
    nodes = [table_chunk("base-1", "cnae20.csv", "table:base"), table_chunk("base-2", "cnae20.csv", "table:base"),
             table_chunk("dic-1", "dicvar_cnae20.csv", "table:dic")]
    inject_deterministic_triplets(store, nodes, structural=True)
    edges = [r for r in store.graph.relations.values() if r.label == "DICIONARIO_DE"]
    assert [(e.source_id, e.properties["method"]) for e in edges] == [("dic-1", "filename_convention")]
    base_entity = next(e for e in store.graph.nodes.values() if getattr(e, "name", "") == "table:base")
    assert edges[0].target_id == base_entity.id
