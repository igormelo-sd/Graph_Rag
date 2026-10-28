"""Resumo do grafo persistido: contagens, status e motivos de rejeição da extração.

Não chama LLM nem altera o grafo. Os números descrevem o que foi extraído e
aceito pelas checagens heurísticas; não medem acerto semântico.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]


def _reason(item):
    text = item.get("reason", "") if isinstance(item, dict) else str(item)
    # Agrupa por motivo, sem o detalhe variável depois de ":" ou "(".
    return re.split(r"[:(]", text, maxsplit=1)[0].strip() or "sem motivo"


def _json(value, default):
    try:
        return json.loads(value) if isinstance(value, str) else default
    except ValueError:
        return default


def audit(graph_store):
    nodes, relations = graph_store.graph.nodes, graph_store.graph.relations
    report = {"nodes": len(nodes), "relations": len(relations),
              "node_labels": Counter(), "relation_labels": Counter(), "relation_methods": Counter(),
              "semantic_status": Counter(), "polarity": Counter(), "modality": Counter(),
              "observation_status": Counter(), "observation_issues": Counter(),
              "extraction": {"chunks_audited": 0, "accepted": 0, "rejected": 0, "rejection_reasons": Counter()}}
    for node in nodes.values():
        report["node_labels"][node.label] += 1
        properties = getattr(node, "properties", {}) or {}
        if node.label == "ObservacaoEstatistica":
            report["observation_status"][properties.get("status", "desconhecido")] += 1
            for issue in _json(properties.get("issues_json"), []):
                report["observation_issues"][str(issue).split(":", 1)[0]] += 1
        audit_raw = properties.get("ontology_extraction_audit")
        if audit_raw:
            data = _json(audit_raw, {})
            report["extraction"]["chunks_audited"] += 1
            report["extraction"]["accepted"] += int(data.get("accepted", 0) or 0)
            for item in data.get("rejected", []):
                report["extraction"]["rejected"] += 1
                report["extraction"]["rejection_reasons"][_reason(item)] += 1
    for relation in relations.values():
        properties = relation.properties or {}
        report["relation_labels"][relation.label] += 1
        report["relation_methods"][properties.get("method", "sem método")] += 1
        if properties.get("source_node_id") and relation.label != "HAS_ENTITY":
            report["semantic_status"][properties.get("semantic_status", "sem status")] += 1
            report["polarity"][properties.get("polarity", "sem polaridade")] += 1
            report["modality"][properties.get("modality", "sem modalidade")] += 1

    def ordered(value):
        if isinstance(value, Counter):
            return dict(value.most_common())
        if isinstance(value, dict):
            return {key: ordered(item) for key, item in value.items()}
        return value
    return ordered(report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", default=os.getenv("RAG_GRAPH_DIR") or str(ROOT / "graph_store"),
                        help="diretório do grafo ou caminho de graph_store.json")
    parser.add_argument("--output", help="grava o JSON neste arquivo em vez de imprimir")
    args = parser.parse_args()
    path = Path(args.graph)
    if path.is_dir():
        path = path / "graph_store.json"
    from graph_indexing import _load_graph_store
    payload = json.dumps(audit(_load_graph_store(str(path))), ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
