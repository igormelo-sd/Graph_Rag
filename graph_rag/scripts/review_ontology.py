"""Revisão humana das propostas de tipos geradas por RAG_ONTOLOGY_DISCOVER=1.

Sem --approve, apenas lista as propostas e seus trechos. Com --approve, copia
os tipos nomeados para config/ontology_extensions.json com reviewed=true.
Nada é aprovado automaticamente.
"""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposals", default=str(Path(os.getenv("RAG_GRAPH_DIR") or ROOT / "graph_store") / "ontology.json"))
    parser.add_argument("--extensions", default=os.getenv("RAG_ONTOLOGY_EXTENSIONS") or str(ROOT / "config" / "ontology_extensions.json"))
    parser.add_argument("--approve", nargs="*", default=[], metavar="NOME", help="tipos propostos a aprovar")
    args = parser.parse_args()
    proposals = {item["name"]: item for item in json.loads(Path(args.proposals).read_text(encoding="utf-8")).get("entity_types", [])}
    if not args.approve:
        for name, item in proposals.items():
            print(f"{name} (pai: {item['parent']}): {item['description']}\n  trecho: {item['evidence']}\n")
        print(f"{len(proposals)} proposta(s). Use --approve NOME para aprovar.")
        return
    missing = [name for name in args.approve if name not in proposals]
    if missing:
        raise SystemExit("Propostas inexistentes: " + ", ".join(missing))
    path = Path(args.extensions)
    data = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    from domain_ontology import SCHEMA_VERSION, _extensions_from_text
    data.setdefault("schema_version", SCHEMA_VERSION)
    current = {item.get("name"): item for item in data.setdefault("entity_types", [])}
    for name in args.approve:
        item = proposals[name]
        current[name] = {"name": name, "description": item["description"], "parent": item["parent"],
                         "evidence": item["evidence"], "reviewed": True}
    data["entity_types"] = list(current.values())
    raw = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    _extensions_from_text(raw)  # Mesma validação usada na carga; falha antes de gravar.
    temporary = path.with_suffix(".tmp")
    temporary.write_text(raw, encoding="utf-8")
    temporary.replace(path)
    print(f"Aprovados: {', '.join(args.approve)}. O hash da ontologia mudou: anotações refeitas e grafo reconstruído, sem novos embeddings.")


if __name__ == "__main__":
    main()
