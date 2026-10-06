"""Extração JSON com definições e validação explícita antes de inserir relações."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from llama_index.core.schema import TransformComponent
from llama_index.core.graph_stores.types import EntityNode, Relation, KG_NODES_KEY, KG_RELATIONS_KEY
from domain_ontology import entity_definitions, RELATIONS, validate_relation, fold, TERRITORIES, INDICATORS, facets, SECTOR_LABELS
from structured_output import parse_json_object, StructuredOutputError
from logger import get_logger
from relation_semantics import relation_attributes

log = get_logger(__name__)


def canonical_name(name, entity_type):
    normalized = fold(name).strip()
    for key, definition in TERRITORIES.items():
        if normalized in {key, fold(definition["name"])} and entity_type == definition["type"]:
            return definition["name"]
    if entity_type == "Indicador":
        import re
        matches = [label for pattern, label, _ in INDICATORS.values() if re.search(pattern, normalized)]
        if len(matches) == 1:
            return matches[0]
    if entity_type == "Setor":
        sectors = facets(name)["sector"]
        if len(sectors) == 1:
            return SECTOR_LABELS[next(iter(sectors))]
    return str(name).strip()


class OntologyPathExtractor(TransformComponent):
    llm: Any
    max_triplets: int = 6

    def __call__(self, nodes, **kwargs):
        definitions = entity_definitions()
        schema = {key: {"domain": a, "range": b} for key, (a, b) in RELATIONS.items()}
        for node in nodes:
            prompt = (
                "Extraia relações explicitamente sustentadas pelo trecho. Não invente valores, causalidade ou identidade territorial. "
                "Não crie observações numéricas: elas são extraídas separadamente com proveniência. "
                "Não converta negação em afirmação, correlação em causalidade ou hipótese em fato. "
                "CAUSA exige afirmação causal literal; ASSOCIADO_A exige associação literal. "
                "Cada entidade deve ter nome presente no trecho. Retorne JSON "
                '{"triples":[{"subject":{"name":"...","type":"..."},"relation":"...",'
                '"object":{"name":"...","type":"..."},"evidence":"citação literal do trecho"}]}. '
                f"Máximo {self.max_triplets} relações. Definições: " + json.dumps(definitions, ensure_ascii=False)
                + "\nCombinações permitidas: " + json.dumps(schema, ensure_ascii=False)
                + "\nTrecho:\n" + node.text[:6000]
            )
            accepted_nodes, accepted_relations, rejected = [], [], []
            try:
                payload = parse_json_object(self.llm.complete(prompt).text)
                triples = payload.get("triples", [])
                if not isinstance(triples, list):
                    raise ValueError("triples deve ser lista")
                for triple in triples[:self.max_triplets]:
                    try:
                        if not isinstance(triple, dict):
                            raise ValueError("Tripla deve ser objeto")
                        subject, obj, relation = triple["subject"], triple["object"], triple["relation"]
                        if any(not isinstance(entity, dict) or not isinstance(entity.get("type"), str)
                               for entity in (subject, obj)) or not isinstance(relation, str):
                            raise ValueError("Entidades e relação com formato inválido")
                        evidence = triple["evidence"]
                        if not isinstance(evidence, str) or len(evidence.strip()) < 8 or evidence not in node.text:
                            raise ValueError("Trecho de apoio literal ausente")
                        if not validate_relation(subject["type"], relation, obj["type"]):
                            raise ValueError("Combinação de tipos não permitida")
                        if any(not isinstance(entity.get("name"), str) or not 1 <= len(entity["name"]) <= 160
                               or fold(entity["name"]) not in fold(evidence) for entity in (subject, obj)):
                            raise ValueError("Entidade não sustentada pelo trecho citado")
                        attributes = relation_attributes(relation, evidence, node.metadata, node.node_id)
                        entities = [EntityNode(name=e["type"] + ":" + canonical_name(e["name"], e["type"]), label=e["type"],
                                               properties={"evidence": evidence, "extraction_status": "candidate"}) for e in (subject, obj)]
                        accepted_nodes.extend(entities)
                        accepted_relations.append(Relation(label=relation, source_id=entities[0].id, target_id=entities[1].id,
                                                           properties=attributes))
                    except (KeyError, TypeError, ValueError) as exc:
                        rejected.append({"reason": str(exc), "candidate": triple})
            except (StructuredOutputError, ValueError, TypeError) as exc:
                rejected.append("Saída inválida: " + str(exc))
            except Exception as exc:
                # Falha externa pode ativar fallback do construtor; não salvar cache completo.
                log.warning("Extração ontológica falhou no chunk %s: %s", node.node_id, exc)
                raise
            node.metadata[KG_NODES_KEY] = accepted_nodes
            node.metadata[KG_RELATIONS_KEY] = accepted_relations
            node.metadata["ontology_extraction_audit"] = json.dumps({"accepted": len(accepted_relations),
                "relations": [{"source": relation.source_id, "relation": relation.label, "target": relation.target_id,
                               "attributes": relation.properties} for relation in accepted_relations], "rejected": rejected}, ensure_ascii=False)
            for key in ("ontology_extraction_audit",):
                node.excluded_embed_metadata_keys = list(dict.fromkeys(node.excluded_embed_metadata_keys + [key]))
                node.excluded_llm_metadata_keys = list(dict.fromkeys(node.excluded_llm_metadata_keys + [key]))
        return nodes

    async def acall(self, nodes, **kwargs):
        return await asyncio.to_thread(self.__call__, nodes, **kwargs)
