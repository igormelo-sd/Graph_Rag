"""Extensões de vocabulário, entidades canônicas, cache de extração e ordenação de observações."""
import json
from types import SimpleNamespace

import pytest
from llama_index.core.graph_stores import SimplePropertyGraphStore
from llama_index.core.schema import TextNode

import domain_ontology
from domain_ontology import facets, territories, fingerprint, TERRITORIES, INDICATORS


@pytest.fixture
def extensions(tmp_path, monkeypatch):
    path = tmp_path / "ontology_extensions.json"
    monkeypatch.setenv("RAG_ONTOLOGY_EXTENSIONS", str(path))

    def write(**items):
        path.write_text(json.dumps({"schema_version": domain_ontology.SCHEMA_VERSION, **items}), encoding="utf-8")
        return path
    yield write
    monkeypatch.undo()
    domain_ontology._sync_vocabulary()  # Restaura o cadastro base para os demais testes.


def test_extensao_revisada_amplia_indicadores_e_territorios(extensions):
    before = fingerprint()
    extensions(indicators=[{"id": "arrecadacao", "label": "Arrecadação", "pattern": r"arrecadac\w*", "kind": "fluxo", "reviewed": True},
                           {"id": "ignorado", "label": "Ignorado", "pattern": "ignorado", "reviewed": False}],
               territories=[{"id": "municipio_campinas", "name": "Município de Campinas", "type": "Municipio",
                             "parent": "estado_sp", "pattern": r"municipio de campinas", "reviewed": True}])
    found = facets("Arrecadação no Município de Campinas em 2023")
    assert found["indicator"] == {"arrecadacao"} and found["region"] == {"municipio_campinas"}
    assert TERRITORIES["municipio_campinas"]["parent"] == "estado_sp"
    assert "ignorado" not in INDICATORS
    assert fingerprint() != before


def test_extensao_removida_restaura_cadastro_base(extensions):
    path = extensions(indicators=[{"id": "arrecadacao", "label": "Arrecadação", "pattern": "arrecadacao", "reviewed": True}])
    assert "arrecadacao" in facets("arrecadacao")["indicator"]
    path.unlink()
    assert facets("arrecadacao")["indicator"] == set()
    assert "arrecadacao" not in INDICATORS


@pytest.mark.parametrize("item", [{"id": "pib", "label": "PIB", "pattern": "pib", "reviewed": True},
                                  {"id": "novo", "label": "Novo", "pattern": "produção", "reviewed": True},
                                  {"id": "novo", "label": "Novo", "pattern": "(", "reviewed": True}])
def test_extensao_invalida_e_recusada(extensions, item):
    extensions(indicators=[item])
    with pytest.raises(ValueError):
        facets("qualquer texto")


def test_territorio_estendido_exige_pai_cadastrado(extensions):
    extensions(territories=[{"id": "municipio_x", "name": "Município X", "type": "Municipio", "parent": "inexistente",
                             "pattern": "municipio x", "reviewed": True}])
    with pytest.raises(ValueError, match="pai"):
        territories("Município X")


def test_facetas_em_cache_devolvem_copias_independentes():
    first = facets("Taxa de desocupação em 2023")
    first["period"].add("1999")
    assert facets("Taxa de desocupação em 2023")["period"] == {"2023"}


def test_entidade_canonica_usa_tipo_e_periodo_do_cadastro():
    from ontology_extractor import canonical_entity
    assert canonical_entity("Estado de São Paulo", "Territorio") == ("Estado", "Estado de São Paulo", "estado_sp")
    assert canonical_entity("2º trimestre de 2023", "Período") == ("Período", "2023-Q2", "2023-Q2")
    assert canonical_entity("emprego formal", "Indicador") == ("Indicador", "Emprego", "emprego")
    assert canonical_entity("algo novo", "Indicador") == ("Indicador", "algo novo", None)


class CountingLLM:
    def __init__(self, response):
        self.calls, self.response, self.model = 0, response, "modelo-teste"

    def complete(self, prompt):
        self.calls += 1
        return SimpleNamespace(text=self.response)


def triple(evidence):
    return json.dumps({"triples": [{"subject": {"name": "emprego", "type": "Indicador"}, "relation": "CRESCEU_EM",
                                    "object": {"name": "2023", "type": "Período"}, "evidence": evidence}]})


def test_cache_de_extracao_evita_nova_chamada_e_revalida(tmp_path):
    from llama_index.core.graph_stores.types import KG_RELATIONS_KEY, KG_NODES_KEY
    from ontology_extractor import OntologyPathExtractor
    llm = CountingLLM(triple("O emprego cresceu em 2023."))
    cache = str(tmp_path / "extraction_cache.jsonl")
    for _ in range(2):
        node = TextNode(id_="a", text="O emprego cresceu em 2023.", metadata={"source_file": "fonte.pdf", "page": 1})
        OntologyPathExtractor(llm=llm, cache_path=cache)([node])
    assert llm.calls == 1
    relation = node.metadata[KG_RELATIONS_KEY][0]
    assert relation.source_id == "Indicador:Emprego" and relation.target_id == "Período:2023"
    assert {entity.properties.get("canonical_id") for entity in node.metadata[KG_NODES_KEY]} == {"emprego", "2023"}


def test_cache_de_extracao_ignora_linha_parcial(tmp_path):
    from ontology_extractor import _load_cache
    path = tmp_path / "cache.jsonl"
    path.write_text(json.dumps({"key": "k", "response": "{}"}) + "\n{\"key\": \"parcial", encoding="utf-8")
    assert _load_cache(str(path)) == {"k": "{}"}


def test_relacao_negada_e_preservada_sem_virar_afirmacao():
    from llama_index.core.graph_stores.types import KG_RELATIONS_KEY
    from ontology_extractor import OntologyPathExtractor
    node = TextNode(id_="a", text="O emprego não cresceu em 2023.", metadata={})
    OntologyPathExtractor(llm=CountingLLM(triple("O emprego não cresceu em 2023.")))([node])
    attributes = node.metadata[KG_RELATIONS_KEY][0].properties
    assert attributes["polarity"] == "negated" and attributes["literal_assertion"] is False


def test_comparacao_nao_e_sujeito_de_crescimento_no_corpus():
    from domain_ontology import validate_relation, RELATIONS
    assert validate_relation("Indicador", "CRESCEU_EM", "Período")
    assert not validate_relation("Comparacao", "CRESCEU_EM", "Período")
    assert "PERTENCE_A" not in RELATIONS


def observation_graph():
    from llama_index.core.graph_stores.types import EntityNode, Relation
    from graph_retriever import GraphRetriever
    store = SimplePropertyGraphStore()
    base = {"indicator": ["desocupacao"], "region": ["estado_sp"], "period": ["2023"], "unit": ["percentual"],
            "scale": [], "sector": [], "source": [], "basis": [], "kind": ["taxa"]}
    variants = {"sem-cobertura": {"coverage": []}, "informal": {"coverage": ["informal"]}, "total": {"coverage": ["total"]}}
    for name, extra in variants.items():
        chunk = TextNode(id_=f"chunk-{name}", text=f"Taxa de desocupação {name}: 7,9% em 2023.")
        observation = EntityNode(name=f"obs-{name}", label="ObservacaoEstatistica", properties={
            "dimensions_json": json.dumps({**base, **extra}), "status": "structured_candidate", "issues_json": "[]"})
        store.upsert_llama_nodes([chunk])
        store.upsert_nodes([observation])
        store.upsert_relations([Relation(label="SUSTENTADA_POR", source_id=observation.id, target_id=chunk.node_id)])
    return GraphRetriever(SimpleNamespace(property_graph_store=store), llm=None, use_llm=False)


def test_cobertura_ordena_sem_excluir_observacoes():
    result = observation_graph()._retrieve_observations("Taxa de desocupação total no Estado de São Paulo em 2023")
    # Antes, "total" era filtro obrigatório e só a observação "total" voltava.
    assert [node.node_id for node in result] == ["chunk-total", "chunk-sem-cobertura", "chunk-informal"]


def test_comunidades_ignoram_relacao_negada():
    from llama_index.core.graph_stores.types import EntityNode, Relation
    from community_search import detect_communities
    store = SimplePropertyGraphStore()
    first, second = EntityNode(name="Indicador:PIB", label="Indicador"), EntityNode(name="Indicador:Emprego", label="Indicador")
    store.upsert_nodes([first, second])
    store.upsert_relations([Relation(label="CAUSA", source_id=first.id, target_id=second.id,
                                     properties={"source_node_id": "a", "polarity": "negated"})])
    nodes = [SimpleNamespace(node_id="a", text="O PIB não causou emprego.", metadata={})]
    records = detect_communities(store, nodes)
    assert all(len(record.get("entities", [])) <= 1 for record in records)


def test_relatorio_de_auditoria_agrupa_rejeicoes_e_polaridade():
    from llama_index.core.graph_stores.types import EntityNode, Relation
    from scripts.graph_audit_report import audit
    store = SimplePropertyGraphStore()
    chunk = TextNode(id_="a", text="O emprego não cresceu em 2023.", metadata={"ontology_extraction_audit": json.dumps(
        {"accepted": 1, "rejected": [{"reason": "Combinação de tipos não permitida"}, "Saída inválida: JSON"]})})
    store.upsert_llama_nodes([chunk])
    first, second = EntityNode(name="Indicador:Emprego", label="Indicador"), EntityNode(name="Período:2023", label="Período")
    store.upsert_nodes([first, second])
    store.upsert_relations([Relation(label="CRESCEU_EM", source_id=first.id, target_id=second.id,
                                     properties={"source_node_id": "a", "polarity": "negated", "semantic_status": "requires_review"})])
    report = audit(store)
    assert report["extraction"]["rejection_reasons"] == {"Combinação de tipos não permitida": 1, "Saída inválida": 1}
    assert report["polarity"] == {"negated": 1}


def test_exportacao_skos_descreve_relacoes_sem_axiomas_de_dominio():
    from scripts.export_ontology_skos import export
    turtle = export()
    assert "ge:CRESCEU_EM a rdf:Property" in turtle and "schema:domainIncludes ge:Indicador" in turtle
    assert "rdfs:domain" not in turtle
    assert "skos:broader ge:Territorios_estado_sp" in turtle
