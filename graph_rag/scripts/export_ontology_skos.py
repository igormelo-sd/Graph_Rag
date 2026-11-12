"""Exporta o modelo de domínio para Turtle (RDFS/SKOS), para documentação.

O arquivo descreve classes, relações e vocabulários cadastrados, incluindo
extensões revisadas. Não é carregado pela aplicação e não implica inferência:
domínio/alcance usam schema:domainIncludes/rangeIncludes, sem axiomas OWL.
"""
import argparse
from pathlib import Path
import re
import unicodedata
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

PREFIXES = """@prefix ge: <urn:graph-rag:economia#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix schema: <https://schema.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
"""


def local(name):
    """Nome local seguro para Turtle: sem acentos, com a caixa original."""
    plain = "".join(c for c in unicodedata.normalize("NFD", str(name)) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Za-z0-9_]", "_", plain)


def literal(text, language="pt"):
    quoted = '"' + str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'
    return quoted + (f"@{language}" if language else "")


def export():
    import domain_ontology as model
    extensions = model.approved_extensions()
    lines = [PREFIXES, f"ge:Modelo a owl:Ontology ; owl:versionInfo {literal(model.SCHEMA_VERSION, None)} ;",
             f"    rdfs:comment {literal('Fingerprint ' + model.fingerprint() + '; conformidade não prova verdade documental.')} .", ""]
    definitions = model.entity_definitions()
    for name, description in definitions.items():
        parent = model.PARENTS.get(name) or extensions.get(name, {}).get("parent")
        statements = [f"ge:{local(name)} a rdfs:Class", f"rdfs:label {literal(name)}", f"rdfs:comment {literal(description)}"]
        if parent:
            statements.append(f"rdfs:subClassOf ge:{local(parent)}")
        lines.append(" ;\n    ".join(statements) + " .")
    lines.append("")
    for relation, (domain, range_) in model.RELATIONS.items():
        statements = [f"ge:{relation} a rdf:Property", f"rdfs:label {literal(relation)}"]
        statements += [f"schema:domainIncludes ge:{local(kind)}" for kind in domain]
        statements += [f"schema:rangeIncludes ge:{local(kind)}" for kind in range_]
        lines.append(" ;\n    ".join(statements) + " .")
    lines.append("")
    schemes = (("Indicadores", "Indicador", {key: label for key, (_, label, _) in model.INDICATORS.items()}, {}),
               ("Setores", "Setor", model.SECTOR_LABELS, model.SECTOR_PARENTS),
               ("Territorios", "Territorio", {key: item["name"] for key, item in model.TERRITORIES.items()},
                {key: item["parent"] for key, item in model.TERRITORIES.items() if item["parent"]}))
    for scheme, kind, labels, parents in schemes:
        lines.append(f"ge:{scheme} a skos:ConceptScheme ; skos:prefLabel {literal(scheme)} .")
        for key, label in labels.items():
            concept_type = model.TERRITORIES[key]["type"] if kind == "Territorio" else kind
            statements = [f"ge:{scheme}_{local(key)} a skos:Concept, ge:{local(concept_type)}",
                          f"skos:inScheme ge:{scheme}", f"skos:prefLabel {literal(label)}", f"skos:notation {literal(key, None)}"]
            if key in parents:
                statements.append(f"skos:broader ge:{scheme}_{local(parents[key])}")
            lines.append(" ;\n    ".join(statements) + " .")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(ROOT / "docs" / "ontologia.ttl"))
    args = parser.parse_args()
    Path(args.output).write_text(export(), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
