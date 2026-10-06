"""
Graph Indexing — constrói um PropertyGraphIndex de conhecimento sobre os
chunks de texto usando extração de entidades e relações via LLM.

Entidades: Indicador, Setor, Região, Período, FonteDados
Relações:  CRESCEU_EM, RECUOU_EM, PERTENCE_A, APLICA_SE_A, MEDIDO_POR, RELACIONA_COM

O grafo é persistido em {base_dir}/graph_store/ e reutilizado nas execuções
seguintes. É reconstruído automaticamente quando os documentos mudam
(force_rebuild=True).
"""
import os
import json

from llama_index.core import PropertyGraphIndex
from llama_index.core.graph_stores import SimplePropertyGraphStore
from llama_index.core.graph_stores.simple_labelled import LabelledPropertyGraph
from ontology_extractor import OntologyPathExtractor
from domain_ontology import fingerprint, enabled as domain_enabled

from logger import get_logger

try:
    import networkx as nx
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _HAS_NETWORKX = True
except ImportError:
    _HAS_NETWORKX = False

log = get_logger(__name__)

_GRAPH_DIR = "graph_store"
_GRAPH_FILE = "graph_store.json"

def _save_graph_store(graph_store: SimplePropertyGraphStore, path: str) -> None:
    """Persiste o grafo em UTF-8 (contorna limite do cp1252 no Windows)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(graph_store.graph.model_dump_json())


def _load_graph_store(path: str) -> SimplePropertyGraphStore:
    """Carrega o grafo de um JSON salvo em UTF-8."""
    with open(path, "r", encoding="utf-8") as f:
        graph = LabelledPropertyGraph.model_validate_json(f.read())
    return SimplePropertyGraphStore(graph=graph)


def _graph_embed_enabled() -> bool:
    return os.getenv("RAG_GRAPH_EMBED", "0").strip().lower() in {"1", "true", "yes", "on"}


def _graph_struct_enabled() -> bool:
    return os.getenv("RAG_GRAPH_STRUCT", "1").strip().lower() in {"1", "true", "yes", "on"}


def _inject_structural_triplets(graph_store, all_nodes):
    """Estrutura tipada com IDs dos chunks e texto recuperável."""
    from collections import defaultdict
    from llama_index.core.graph_stores.types import EntityNode, Relation
    graph_store.upsert_llama_nodes(all_nodes)
    by_page = defaultdict(list)
    for node in all_nodes:
        md = node.metadata
        by_page[(str(md.get("source_file", "")), str(md.get("page", "")))].append(node)
    for (source, page), nodes in by_page.items():
        if not source or not page:
            continue
        doc = EntityNode(name=f"Documento:{source}", label="Documento")
        pag = EntityNode(name=f"Pagina:{source}#p{page}", label="Pagina")
        graph_store.upsert_nodes([doc, pag])
        graph_store.upsert_relations([Relation(label="PERTENCE_A_DOC", source_id=pag.id, target_id=doc.id)])
        # Tipos separados podem ter chunk_id repetido. Não ligar por uma ordem falsa.
        text_nodes = sorted([n for n in nodes if n.metadata.get("type", "text") == "text"], key=lambda n: int(n.metadata.get("chunk_id") or 0))
        for node in nodes:
            graph_store.upsert_relations([Relation(label="CONTIDA_EM", source_id=node.node_id, target_id=pag.id)])
        for first, second in zip(text_nodes, text_nodes[1:]):
            if int(second.metadata.get("chunk_id") or 0) != int(first.metadata.get("chunk_id") or 0) + 1:
                continue
            graph_store.upsert_relations([
                Relation(label="NEXT_CHUNK", source_id=first.node_id, target_id=second.node_id),
                Relation(label="SAME_PAGE", source_id=first.node_id, target_id=second.node_id),
                Relation(label="SAME_PAGE", source_id=second.node_id, target_id=first.node_id),
            ])
    _inject_document_context(graph_store, all_nodes)


def _inject_document_context(graph_store, all_nodes):
    from document_context import context_links
    from llama_index.core.graph_stores.types import EntityNode, Relation, TRIPLET_SOURCE_KEY
    tables = {}
    for node in all_nodes:
        key = node.metadata.get("table_key")
        if node.metadata.get("type") != "table" or not key:
            continue
        table = tables.setdefault(key, EntityNode(name=key, label="Tabela", properties={"canonical_id": key}))
        graph_store.upsert_nodes([table])
        graph_store.upsert_relations([Relation(label="REPRESENTADA_EM", source_id=table.id, target_id=node.node_id,
                                              properties={TRIPLET_SOURCE_KEY: node.node_id, "method": "table_chunk_identity"})])
    for source, target, relation, properties in context_links(all_nodes):
        table = tables.get(source.metadata.get("table_key"))
        if table is not None:
            graph_store.upsert_relations([Relation(label=relation, source_id=table.id, target_id=target.node_id,
                                                  properties={**properties, TRIPLET_SOURCE_KEY: target.node_id})])


def _inject_domain_triplets(graph_store, all_nodes):
    from llama_index.core.graph_stores.types import EntityNode, Relation, TRIPLET_SOURCE_KEY
    from domain_ontology import enabled, node_observations, validate_relation, TERRITORIES, INDICATORS, SECTOR_PARENTS, SECTOR_LABELS
    if not enabled():
        return
    graph_store.upsert_llama_nodes(all_nodes)
    # Cadastro completo da hierarquia; um pai não precisa ter valor observado para existir.
    for key, definition in TERRITORIES.items():
        territory = EntityNode(name=f"{definition['type']}:{definition['name']}", label=definition["type"], properties={"canonical_id": key})
        graph_store.upsert_nodes([territory])
        if definition["parent"]:
            parent = TERRITORIES[definition["parent"]]
            parent_node = EntityNode(name=f"{parent['type']}:{parent['name']}", label=parent["type"], properties={"canonical_id": definition["parent"]})
            graph_store.upsert_nodes([parent_node])
            graph_store.upsert_relations([Relation(label="PARTE_DE", source_id=territory.id, target_id=parent_node.id,
                                                  properties={"method": "registered_territory_hierarchy"})])
    for child, parent in SECTOR_PARENTS.items():
        first = EntityNode(name=f"Setor:{SECTOR_LABELS[child]}", label="Setor", properties={"canonical_id": child})
        second = EntityNode(name=f"Setor:{SECTOR_LABELS[parent]}", label="Setor", properties={"canonical_id": parent})
        graph_store.upsert_nodes([first, second])
        graph_store.upsert_relations([Relation(label="PARTE_DE", source_id=first.id, target_id=second.id,
                                              properties={"method": "registered_sector_hierarchy"})])
    for node in all_nodes:
        for observation in node_observations(node):
            obs = EntityNode(name=observation["id"], label="ObservacaoEstatistica", properties={
                "value": observation["value"], "dimensions_json": json.dumps(observation["dimensions"], ensure_ascii=False),
                "provenance_json": json.dumps(observation["provenance"], ensure_ascii=False),
                "publication_periods_json": json.dumps(observation.get("publication_periods", [])),
                "issues_json": json.dumps(observation.get("issues", []), ensure_ascii=False),
                "status": observation["status"], TRIPLET_SOURCE_KEY: node.node_id,
            })
            graph_store.upsert_nodes([obs])
            graph_store.upsert_relations([Relation(label="SUSTENTADA_POR", source_id=obs.id, target_id=node.node_id,
                                                  properties={TRIPLET_SOURCE_KEY: node.node_id})])
            for dimension, relation, typ in [("indicator", "OBSERVACAO_DE", "Indicador"), ("period", "REFERENTE_A", "Período"),
                                              ("region", "APLICA_SE_A", "Territorio"), ("unit", "EXPRESSA_EM", "Unidade"),
                                              ("sector", "NO_SETOR", "Setor"), ("source", "MEDIDO_POR", "FonteDados")]:
                values = observation["dimensions"][dimension]
                # Uma relação singular não afirma que todas as combinações são fatos.
                if len(values) != 1:
                    continue
                value = values[0]
                definition = TERRITORIES.get(value) if dimension == "region" else None
                actual_type = definition["type"] if definition else typ
                name = definition["name"] if definition else INDICATORS[value][1] if dimension == "indicator" else SECTOR_LABELS[value] if dimension == "sector" else value
                entity = EntityNode(name=f"{actual_type}:{name}", label=actual_type, properties={"canonical_id": value})
                if validate_relation("ObservacaoEstatistica", relation, actual_type):
                    graph_store.upsert_nodes([entity])
                    graph_store.upsert_relations([Relation(label=relation, source_id=obs.id, target_id=entity.id,
                                                          properties={TRIPLET_SOURCE_KEY: node.node_id})])

def export_graph_image(graph_store: SimplePropertyGraphStore, output_path: str) -> None:
    """Exporta o grafo como PNG usando networkx + matplotlib."""
    if not _HAS_NETWORKX:
        log.warning("[Graph] networkx/matplotlib não instalados — imagem não gerada")
        return

    triplets = graph_store.graph.get_triplets()
    if not triplets:
        log.warning("[Graph] Grafo vazio — imagem não gerada")
        return

    G = nx.DiGraph()
    # triplets é set[str,str,str] ou get_triplets() → [(EntityNode,Relation,EntityNode)]
    # tenta resolver nomes via graph.nodes/relations
    for triplet in triplets[:300]:
        if isinstance(triplet, (list, tuple)) and len(triplet) == 3 and all(hasattr(x, "name") or hasattr(x, "label") for x in triplet):
            src = getattr(triplet[0], "name", str(triplet[0]))
            rel = getattr(triplet[1], "label", str(triplet[1]))
            dst = getattr(triplet[2], "name", str(triplet[2]))
        elif isinstance(triplet, (list, tuple)) and len(triplet) == 3:
            # set de ids
            s_id, r_id, o_id = triplet
            s_node = graph_store.graph.nodes.get(s_id)
            r_node = graph_store.graph.relations.get(r_id)
            o_node = graph_store.graph.nodes.get(o_id)
            src = getattr(s_node, "name", s_id) if s_node else s_id
            rel = getattr(r_node, "label", r_id) if r_node else r_id
            dst = getattr(o_node, "name", o_id) if o_node else o_id
        else:
            src, rel, dst = str(triplet), "", ""
        G.add_edge(src, dst, label=rel)

    fig, ax = plt.subplots(figsize=(24, 18))
    pos = nx.spring_layout(G, seed=42, k=2.5)
    nx.draw_networkx_nodes(G, pos, node_size=300, node_color="#4C9BE8", alpha=0.9, ax=ax)
    nx.draw_networkx_labels(G, pos, font_size=6, font_color="white", ax=ax)
    nx.draw_networkx_edges(G, pos, edge_color="#888", arrows=True, arrowsize=10, ax=ax)
    edge_labels = nx.get_edge_attributes(G, "label")
    nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=5, ax=ax)
    ax.axis("off")
    ax.set_title(f"Knowledge Graph — amostra de até 300 relações ({len(triplets)} no grafo)", fontsize=12)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("[Graph] Imagem salva em %s", output_path)


def build_or_load_graph(
    text_nodes: list,
    base_dir: str,
    llm,
    force_rebuild: bool = False,
    use_llm: bool = False,
) -> PropertyGraphIndex:
    """
    Constrói o PropertyGraphIndex a partir dos nós de texto ou carrega do disco.

    Parâmetros
    ----------
    text_nodes : list
        Nós TextNode já processados (saída de process_documents).
    base_dir : str
        Diretório raiz do RAG (onde fica /chroma_db).
    llm :
        LLM para extração de entidades/relações.
    force_rebuild : bool
        Se True, reconstrói mesmo que o cache exista.

    Retorna
    -------
    PropertyGraphIndex pronto para uso.
    """
    graph_dir = os.getenv("RAG_GRAPH_DIR") or os.path.join(base_dir, _GRAPH_DIR)
    graph_path = os.path.join(graph_dir, _GRAPH_FILE)
    config_path = os.path.join(graph_dir, "graph_config.json")
    from graph_ontology import ontology_enabled
    graph_config = {
        "llm": bool(use_llm),
        "embed": _graph_embed_enabled(),
        "struct": _graph_struct_enabled(),
        "ontology": ontology_enabled(),
        "domain_enabled": domain_enabled(),
        "ontology_hash": fingerprint(),
        "graph_pipeline": "typed-observations-context-v2",
    }
    try:
        with open(config_path, encoding="utf-8") as f:
            force_rebuild = force_rebuild or json.load(f) != graph_config
    except (OSError, ValueError):
        force_rebuild = True

    def save_config():
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(graph_config, f)

    if not force_rebuild and os.path.exists(graph_path):
        try:
            log.info("[Graph] Carregando grafo existente de %s", graph_path)
            graph_store = _load_graph_store(graph_path)
            if not graph_store.graph.triplets:
                log.warning("[Graph] Grafo em cache vazio — reconstruindo")
            else:
                image_path = os.path.join(graph_dir, "graph_store.png")
                if not os.path.exists(image_path):
                    export_graph_image(graph_store, image_path)
                if _graph_struct_enabled():
                    # injeta estruturais mesmo em cache (idempotente, dedup via triplets)
                    try:
                        _inject_structural_triplets(graph_store, text_nodes)
                        _save_graph_store(graph_store, graph_path)
                    except Exception:
                        pass
                _inject_domain_triplets(graph_store, text_nodes)
                _save_graph_store(graph_store, graph_path)
                return PropertyGraphIndex.from_existing(
                    property_graph_store=graph_store,
                    embed_kg_nodes=_graph_embed_enabled(),
                )
        except Exception as exc:
            log.warning("[Graph] Cache inválido (%s) — reconstruindo", exc)

    log.info("[Graph] Construindo grafo de conhecimento...")
    os.makedirs(graph_dir, exist_ok=True)
    # Um fallback estrutural após falha não deve parecer um cache LLM completo.
    if os.path.exists(config_path):
        os.remove(config_path)

    # Usa apenas nós de texto narrativo — tabelas/timeseries têm pouco contexto relacional
    narrative_nodes = [
        n for n in text_nodes
        if getattr(n, "metadata", {}).get("type", "text") == "text"
    ]
    if not narrative_nodes:
        narrative_nodes = text_nodes

    log.info("[Graph] Extraindo entidades e relações de %d nós", len(narrative_nodes))

    # Fast-path P0: quando só estrutural está ativo (custo zero), não chama LLM
    _need_llm_graph = graph_config["llm"]
    if ontology_enabled():
        from graph_ontology import discover_entity_types
        discover_entity_types(text_nodes, llm, base_dir, force=force_rebuild)
    if not _need_llm_graph:
        log.info("[Graph] Modo estrutural apenas (sem LLM) — injetando triplets determinísticos")
        graph_store = SimplePropertyGraphStore()
        if _graph_struct_enabled():
            _inject_structural_triplets(graph_store, text_nodes)
        _inject_domain_triplets(graph_store, text_nodes)
        _save_graph_store(graph_store, graph_path)
        save_config()
        log.info("[Graph] Grafo estrutural salvo em %s (%d triplets)", graph_path, len(graph_store.graph.triplets))
        try:
            export_graph_image(graph_store, os.path.join(graph_dir, "graph_store.png"))
        except Exception:
            pass
        return PropertyGraphIndex.from_existing(
            property_graph_store=graph_store,
            embed_kg_nodes=_graph_embed_enabled(),
        )

    extractor = OntologyPathExtractor(llm=llm, max_triplets=6)

    graph_store = SimplePropertyGraphStore()
    try:
        index = PropertyGraphIndex(
            nodes=narrative_nodes,
            kg_extractors=[extractor],
            property_graph_store=graph_store,
            embed_kg_nodes=_graph_embed_enabled(),
            show_progress=True,
        )
        if _graph_struct_enabled():
            _inject_structural_triplets(graph_store, text_nodes)
        _inject_domain_triplets(graph_store, text_nodes)
        _save_graph_store(graph_store, graph_path)
        save_config()
        log.info("[Graph] Grafo salvo em %s", graph_path)

        image_path = os.path.join(graph_dir, "graph_store.png")
        export_graph_image(graph_store, image_path)
        return index
    except Exception as exc:
        err_msg = str(exc).lower()
        if "429" in err_msg or "credit_balance_exhausted" in err_msg or "quota" in err_msg:
            log.warning("[Graph] Falha de cota LLM (%s) — fallback para grafo estrutural (sem LLM)", exc)
            # DEBUG: nunca retorna vazio se estrutural está habilitado
            if _graph_struct_enabled():
                try:
                    fallback_store = SimplePropertyGraphStore()
                    _inject_structural_triplets(fallback_store, text_nodes)
                    _inject_domain_triplets(fallback_store, text_nodes)
                    _save_graph_store(fallback_store, graph_path)
                    log.info("[Graph] Fallback estrutural salvo (%d triplets)", len(fallback_store.graph.triplets))
                    return PropertyGraphIndex.from_existing(
                        property_graph_store=fallback_store,
                        embed_kg_nodes=False,
                    )
                except Exception as e2:
                    log.warning("[Graph] Fallback estrutural também falhou (%s)", e2)
            return PropertyGraphIndex(
                nodes=[],
                property_graph_store=graph_store,
                embed_kg_nodes=_graph_embed_enabled(),
            )
        raise
