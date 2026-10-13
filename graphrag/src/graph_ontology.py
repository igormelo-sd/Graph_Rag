"""Descoberta propõe extensões; só tipos explicitamente revisados entram no modelo."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from collections import defaultdict
from domain_ontology import CLASSES, fingerprint, approved_extensions, fold
from logger import get_logger
from structured_output import parse_json_object

log = get_logger(__name__)
_FIXED_TYPES = set(CLASSES)


def _ontology_path(base_dir):
    return Path(os.getenv("RAG_GRAPH_DIR") or Path(base_dir) / "graph_store") / "ontology.json"


def ontology_enabled():
    return os.getenv("RAG_ONTOLOGY_DISCOVER", "0").lower() in {"1", "true", "yes", "on"}


def _sample_chunks(nodes, k=12):
    groups = defaultdict(list)
    for node in nodes:
        md = getattr(node, "metadata", {}) or {}
        groups[(str(md.get("source_file", "")), str(md.get("type", "text")))].append(node)
    selected = []
    # Rodízio entre documentos e modalidades; não apenas início/meio/fim do corpus.
    for position in range(k):
        for key in sorted(groups):
            group = groups[key]
            if position < len(group):
                node = group[position]
                selected.append({"file": key[0], "type": key[1], "page": node.metadata.get("page"), "text": node.text[:800]})
                if len(selected) == k:
                    return selected
    return selected


def discover_entity_types(nodes, llm, base_dir, force=False):
    samples = _sample_chunks(nodes)
    corpus_hash = hashlib.sha256("\n".join(str(n.node_id) for n in nodes).encode()).hexdigest()
    signature = {"schema_hash": fingerprint(), "corpus_hash": corpus_hash, "discovery_version": 2}
    path = _ontology_path(base_dir)
    try:
        if not force and path.exists():
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached.get("signature") == signature:
                return list(approved_extensions())
        if not samples:
            return list(approved_extensions())
        prompt = (
            "Proponha até quatro tipos adicionais para este modelo econômico. Não repita tipos existentes. "
            'Retorne JSON {"entity_types":[{"name":"NomeAscii","description":"definição",'
            '"parent":"tipo existente","evidence":"trecho literal de uma amostra"}]}. '
            "Esta saída é uma proposta para revisão, não alteração automática do modelo.\nModelo: "
            + json.dumps(CLASSES, ensure_ascii=False) + "\nAmostras: " + json.dumps(samples, ensure_ascii=False)
        )
        raw = parse_json_object(llm.complete(prompt).text)
        proposals = []
        import re
        for item in raw.get("entity_types", [])[:4]:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "")
            description = item.get("description", "")
            evidence = item.get("evidence", "")
            if (isinstance(name, str) and re.fullmatch(r"[A-Z][A-Za-z]{2,39}", name)
                    and name not in CLASSES and isinstance(description, str) and description.strip()
                    and item.get("parent") in CLASSES and isinstance(evidence, str) and len(evidence) >= 8
                    and any(evidence in sample["text"] for sample in samples)):
                proposals.append({"name": name, "description": description[:1000], "parent": item["parent"],
                                  "evidence": evidence, "reviewed": False})
        payload = {"signature": signature, "entity_types": proposals, "status": "proposed_only", "samples": samples}
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    except Exception as exc:
        # Não grava falha como descoberta vazia válida; permite tentar novamente.
        log.warning("Descoberta ontológica não concluída: %s", exc)
    return list(approved_extensions())
