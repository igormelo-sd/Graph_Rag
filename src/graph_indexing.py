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
from llama_index.core.indices.property_graph import DynamicLLMPathExtractor

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

_ENTITY_TYPES = [
    "Indicador",   # ex: taxa de desocupação, PIB, IPCA, saldo de empregos
    "Setor",       # ex: indústria de transformação, comércio, construção civil
    "Região",      # ex: Estado de SP, RMSP, interior paulista
    "Período",     # ex: 1T2023, 2024, primeiro trimestre de 2022
    "FonteDados",  # ex: CAGED, PNAD Contínua, RAIS, IBGE, SEADE
    "Tabela",      # tabela extraída de PDF/página
    "Grafico",     # gráfico rasterizado
    "Pagina",      # página do documento (source_file#page)
    "Documento",   # arquivo boletim (SpEconomia-YYYY-MM.pdf)
]

_RELATION_TYPES = [
    "CRESCEU_EM",    # indicador cresceu em determinado período/região/setor
    "RECUOU_EM",     # indicador recuou em determinado período/região/setor
    "PERTENCE_A",    # indicador/dado pertence a setor ou categoria
    "APLICA_SE_A",   # dado se aplica a uma região geográfica
    "MEDIDO_POR",    # indicador é medido/divulgado por uma fonte de dados
    "RELACIONA_COM", # indicador se relaciona com outro indicador ou setor
    "CONTIDA_EM",    # Tabela/Grafico/Chunk contida em Pagina
    "PERTENCE_A_DOC",# Pagina pertence a Documento
    "DESCRITA_EM",   # Tabela/Grafico descrita em Texto vizinho (determinística)
    "NEXT_CHUNK",    # Chunk → próximo Chunk na mesma página (costura split)
    "SAME_PAGE",     # Chunk ↔ Chunk mesma página (clique)
]


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


def _inject_structural_triplets(graph_store: SimplePropertyGraphStore, all_nodes: list) -> None:
    """Injeta arestas estruturais CONTIDA_EM/NEXT_CHUNK/SAME_PAGE sem LLM (custo zero).

    Usa metadata já garantida por processing.py: source_file, page, chunk_id, type.
    """
    if not all_nodes:
        return
    try:
        from collections import defaultdict

        # Agrupa por (source_file, page) para cadeia NEXT_CHUNK e clique SAME_PAGE
        by_page: dict[tuple, list] = defaultdict(list)
        for n in all_nodes:
            md = getattr(n, "metadata", {}) or {}
            key = (str(md.get("source_file") or ""), str(md.get("page") or ""))
            by_page[key].append(n)
        # Usa LabelledPropertyGraph.add_triplet com EntityNode/Relation
        from llama_index.core.graph_stores.simple_labelled import EntityNode, Relation
        import hashlib

        def _add_triplet(subj: str, rel: str, obj: str):
            try:
                # ids determinísticos estáveis
                subj_id = hashlib.md5(subj.encode()).hexdigest()[:12]
                obj_id = hashlib.md5(obj.encode()).hexdigest()[:12]
                rel_id = hashlib.md5(f"{subj}::{rel}::{obj}".encode()).hexdigest()[:12]
                subj_node = EntityNode(id=subj_id, name=subj, label=subj.split(":")[0] if ":" in subj else "Entidade", properties={})
                obj_node = EntityNode(id=obj_id, name=obj, label=obj.split(":")[0] if ":" in obj else "Entidade", properties={})
                relation = Relation(id=rel_id, label=rel, source_id=subj_id, target_id=obj_id, properties={})
                graph_store.graph.add_triplet((subj_node, relation, obj_node))
            except Exception:
                pass

        for (src_file, page), nodes in by_page.items():
            # ordena por chunk_id para NEXT_CHUNK
            try:
                nodes_sorted = sorted(nodes, key=lambda n: int((getattr(n, "metadata", {}) or {}).get("chunk_id") or 0))
            except Exception:
                nodes_sorted = nodes
            pagina_id = f"{src_file}#p{page}"
            doc_id = src_file
            # Pagina -> Documento
            _add_triplet(pagina_id, "PERTENCE_A_DOC", doc_id)
            for idx, n in enumerate(nodes_sorted):
                md = getattr(n, "metadata", {}) or {}
                node_label = f"{md.get('type','text')}:{md.get('chunk_id','?')}@{pagina_id}"
                # Chunk/Tabela/Grafico -> Pagina
                _add_triplet(node_label, "CONTIDA_EM", pagina_id)
                # NEXT_CHUNK cadeia
                if idx + 1 < len(nodes_sorted):
                    nxt = nodes_sorted[idx + 1]
                    nxt_label = f"{nxt.metadata.get('type','text')}:{nxt.metadata.get('chunk_id','?')}@{pagina_id}"
                    _add_triplet(node_label, "NEXT_CHUNK", nxt_label)
                # SAME_PAGE clique (todos com todos na mesma página, até 3 para não explodir)
                # só liga aos 2 vizinhos mais próximos para manter path_depth=2 barato
                for j in (idx - 1, idx + 1):
                    if 0 <= j < len(nodes_sorted) and j != idx:
                        other = nodes_sorted[j]
                        other_label = f"{other.metadata.get('type','text')}:{other.metadata.get('chunk_id','?')}@{pagina_id}"
                        _add_triplet(node_label, "SAME_PAGE", other_label)
                # DESCRITA_EM determinística: Tabela/Grafico -> Texto vizinho mesma página (janela ±1)
                if md.get("type") in {"table", "image"}:
                    for j in (idx - 1, idx + 1):
                        if 0 <= j < len(nodes_sorted):
                            other = nodes_sorted[j]
                            if other.metadata.get("type") == "text":
                                other_label = f"text:{other.metadata.get('chunk_id','?')}@{pagina_id}"
                                _add_triplet(node_label, "DESCRITA_EM", other_label)
                    # LLM secundário quando RAG_GRAPH_DESCRITA_LLM=1 é tratado em startup (não aqui)
        log.info("[Graph] Injetadas arestas estruturais NEXT_CHUNK/CONTIDA_EM para %d páginas", len(by_page))
    except Exception as exc:
        log.warning("[Graph] Falha ao injetar estruturais: %s", exc)


def export_graph_image(graph_store: SimplePropertyGraphStore, output_path: str) -> None:
    """Exporta o grafo como PNG usando networkx + matplotlib."""
    if not _HAS_NETWORKX:
        log.warning("[Graph] networkx/matplotlib não instalados — imagem não gerada")
        return

    triplets = graph_store.graph.triplets
    if not triplets:
        log.warning("[Graph] Grafo vazio — imagem não gerada")
        return

    G = nx.DiGraph()
    # triplets é set[str,str,str] ou get_triplets() → [(EntityNode,Relation,EntityNode)]
    # tenta resolver nomes via graph.nodes/relations
    for triplet in triplets:
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
    ax.set_title(f"Knowledge Graph — {G.number_of_nodes()} nós, {G.number_of_edges()} arestas", fontsize=12)

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
        "llm": bool(use_llm or _graph_embed_enabled() or ontology_enabled()),
        "embed": _graph_embed_enabled(),
        "struct": _graph_struct_enabled(),
        "ontology": ontology_enabled(),
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
    try:
        from graph_ontology import ontology_enabled
        if ontology_enabled():
            _need_llm_graph = True
    except Exception:
        pass
    if not _need_llm_graph:
        log.info("[Graph] Modo estrutural apenas (sem LLM) — injetando triplets determinísticos")
        graph_store = SimplePropertyGraphStore()
        _inject_structural_triplets(graph_store, text_nodes)
        _save_graph_store(graph_store, graph_path)
        save_config()
        log.info("[Graph] Grafo estrutural salvo em %s (%d triplets)", graph_path, len(graph_store.graph.triplets))
        try:
            export_graph_image(graph_store, os.path.join(graph_dir, "graph_store.png"))
        except Exception:
            pass
        return PropertyGraphIndex.from_existing(
            property_graph_store=graph_store,
            embed_kg_nodes=False,
        )

    # P2: ontologia dinâmica opcional (RAG_ONTOLOGY_DISCOVER=1) — port kg ontology.py
    try:
        from graph_ontology import discover_entity_types, ontology_enabled
        if ontology_enabled():
            extra = discover_entity_types(narrative_nodes, llm, base_dir, force=force_rebuild)
            allowed_entities = list(_ENTITY_TYPES) + extra
            if extra:
                log.info("[Graph] Entidades estendidas via ontologia: %s", allowed_entities)
        else:
            allowed_entities = list(_ENTITY_TYPES)
    except Exception as exc:
        log.warning("[Graph] Ontologia desabilitada/falhou (%s) — usando fixos", exc)
        allowed_entities = list(_ENTITY_TYPES)

    extractor = DynamicLLMPathExtractor(
        llm=llm,
        max_triplets_per_chunk=6,
        allowed_entity_types=allowed_entities,
        allowed_relation_types=_RELATION_TYPES,
    )

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
