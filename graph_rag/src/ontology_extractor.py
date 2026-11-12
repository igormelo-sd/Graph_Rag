"""Extração JSON com definições e validação explícita antes de inserir relações."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import threading
from typing import Any

from llama_index.core.schema import TransformComponent
from llama_index.core.graph_stores.types import EntityNode, Relation, KG_NODES_KEY, KG_RELATIONS_KEY
from domain_ontology import (entity_definitions, RELATIONS, validate_relation, fold, TERRITORIES, INDICATORS,
                             facets, territories, periods, is_type, SECTOR_LABELS)
from structured_output import parse_json_object, StructuredOutputError
from logger import get_logger
from relation_semantics import relation_attributes

log = get_logger(__name__)
_CACHE_LOCK = threading.Lock()
_PROMPT_VERSION = 2


def canonical_entity(name, entity_type):
    """Tipo, nome e id do cadastro; sem correspondência única, mantém o literal."""
    normalized = fold(name).strip()
    if is_type(entity_type, "Territorio"):
        matches = {key for key, definition in TERRITORIES.items() if normalized in {key, fold(definition["name"])}}
        matches = matches or territories(name)[0]
        if len(matches) == 1:
            # O cadastro decide Estado/Município/Região; o LLM só indica que é território.
            key = next(iter(matches))
            return TERRITORIES[key]["type"], TERRITORIES[key]["name"], key
    if entity_type == "Indicador":
        matches = [key for key, (pattern, _, _) in INDICATORS.items() if re.search(pattern, normalized)]
        if len(matches) == 1:
            return entity_type, INDICATORS[matches[0]][1], matches[0]
    if entity_type == "Setor":
        sectors = facets(name)["sector"]
        if len(sectors) == 1:
            key = next(iter(sectors))
            return entity_type, SECTOR_LABELS[key], key
    if entity_type == "Período":
        values = periods(name)
        if len(values) == 1:
            # Mesmo nome do nó de período criado pelas observações.
            value = next(iter(values))
            return entity_type, value, value
    return entity_type, str(name).strip(), None


def canonical_name(name, entity_type):
    return canonical_entity(name, entity_type)[1]


def _load_cache(path):
    cache = {}
    if not path or not os.path.exists(path):
        return cache
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            try:
                record = json.loads(line)
                cache[record["key"]] = record["response"]
            except (ValueError, KeyError, TypeError):
                continue  # Linha parcial de uma gravação interrompida.
    return cache


def _append_cache(path, key, response):
    with _CACHE_LOCK:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps({"key": key, "response": response}, ensure_ascii=False) + "\n")


class OntologyPathExtractor(TransformComponent):
    llm: Any
    max_triplets: int = 6
    # Respostas brutas por prompt; a validação é refeita a cada uso.
    cache_path: str | None = None

    def _model_identity(self):
        metadata = getattr(self.llm, "metadata", None)
        return str(getattr(self.llm, "model", "") or getattr(metadata, "model_name", "") or type(self.llm).__name__)

    def __call__(self, nodes, **kwargs):
        definitions = entity_definitions()
        schema = {key: {"domain": a, "range": b} for key, (a, b) in RELATIONS.items()}
        cache = _load_cache(self.cache_path)
        model = self._model_identity()
        for node in nodes:
            prompt = (
                "Extraia relações explicitamente sustentadas pelo trecho. Não invente valores, causalidade ou identidade territorial. "
                "Não crie observações numéricas: elas são extraídas separadamente com proveniência. "
                "Relações negadas no trecho podem ser extraídas: a citação literal define a polaridade. "
                "Não converta correlação em causalidade nem hipótese em fato. "
                "CAUSA exige afirmação causal literal; ASSOCIADO_A exige associação literal. "
                "Cada entidade deve ter nome presente no trecho. Retorne JSON "
                '{"triples":[{"subject":{"name":"...","type":"..."},"relation":"...",'
                '"object":{"name":"...","type":"..."},"evidence":"citação literal do trecho"}]}. '
                f"Máximo {self.max_triplets} relações. Definições: " + json.dumps(definitions, ensure_ascii=False)
                + "\nCombinações permitidas: " + json.dumps(schema, ensure_ascii=False)
                + "\nTrecho:\n" + node.text[:6000]
            )
            key = hashlib.sha256(json.dumps([_PROMPT_VERSION, model, prompt], ensure_ascii=False).encode()).hexdigest()
            accepted_nodes, accepted_relations, rejected = [], [], []
            try:
                response = cache.get(key)
                if response is None:
                    response = self.llm.complete(prompt).text
                    if self.cache_path:
                        _append_cache(self.cache_path, key, response)
                        cache[key] = response
                payload = parse_json_object(response)
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
                        if any(not isinstance(entity.get("name"), str) or not 1 <= len(entity["name"]) <= 160
                               or fold(entity["name"]) not in fold(evidence) for entity in (subject, obj)):
                            raise ValueError("Entidade não sustentada pelo trecho citado")
                        resolved = [canonical_entity(e["name"], e["type"]) for e in (subject, obj)]
                        # Valida com o tipo cadastrado, não com o rótulo proposto pelo LLM.
                        if not validate_relation(resolved[0][0], relation, resolved[1][0]):
                            raise ValueError("Combinação de tipos não permitida")
                        attributes = relation_attributes(relation, evidence, node.metadata, node.node_id)
                        entities = [EntityNode(name=f"{kind}:{name}", label=kind,
                                               properties={"evidence": evidence, "extraction_status": "candidate",
                                                           **({"canonical_id": identity} if identity else {})})
                                    for kind, name, identity in resolved]
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
