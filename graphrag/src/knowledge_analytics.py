"""Cobertura e divergências candidatas; ausência no índice não prova ausência no mundo."""
from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import itertools
import json
import re

from domain_ontology import TERRITORIES, SECTOR_PARENTS, facets, fold, node_observations, enabled

COMPARABILITY = ("indicator", "region", "period", "unit", "scale", "sector", "source", "kind", "basis", "coverage")


def literal_decimal(value):
    raw = str(value).strip().replace("%", "").replace("−", "-").strip()
    if not re.fullmatch(r"-?\d+(?:\.\d{3})*(?:,\d+)?", raw):
        raise ValueError("Valor literal ambíguo")
    return Decimal(raw.replace(".", "").replace(",", "."))


def descendants(parent, registry):
    result, pending = set(), [parent]
    while pending:
        current = pending.pop()
        for child, definition in registry.items():
            ancestor = definition.get("parent") if isinstance(definition, dict) else definition
            if ancestor == current and child not in result:
                result.add(child)
                pending.append(child)
    return result


def hierarchy_scope(question):
    text, dimensions = fold(question), facets(question)
    regions, sectors = set(), set()
    geographic = bool(dimensions["region"] and re.search(r"\b(?:municipios|cidades|regioes|territorios)\b", text))
    sectoral = bool(dimensions["sector"] and re.search(r"\b(?:subsetores|ramos|atividades|segmentos)\b", text))
    if geographic:
        for parent in dimensions["region"]:
            regions |= descendants(parent, TERRITORIES)
        if re.search(r"\b(?:municipios|cidades)\b", text):
            regions = {key for key in regions if TERRITORIES[key]["type"] == "Municipio"}
        elif re.search(r"\bregioes\b", text):
            regions = {key for key in regions if TERRITORIES[key]["type"] == "Região"}
    if sectoral:
        for parent in dimensions["sector"]:
            sectors |= descendants(parent, SECTOR_PARENTS)
    return {"requested": geographic or sectoral, "region": regions, "sector": sectors,
            "region_requested": geographic, "sector_requested": sectoral}


def clarification_request(question, available_regions=()):
    from domain_ontology import query_constraints
    if not enabled():
        return None
    constraints = query_constraints(question)
    if not constraints["ambiguities"] or not constraints["dimensions"]["indicator"]:
        return None
    options = [{"id": key, "label": TERRITORIES[key]["name"], "has_indexed_observations": key in available_regions}
               for key in ("estado_sp", "municipio_sp", "rmsp", "interior_sp")]
    return {"required": True, "dimension": "region", "reason": "ambiguous_sao_paulo",
            "question": "Você se refere ao Estado de São Paulo, ao município, à Região Metropolitana ou ao Interior paulista?",
            "options": options}


def observation_matches(observation, question="", wanted=None, scope=None):
    wanted = facets(question) if wanted is None else wanted
    scope = hierarchy_scope(question) if scope is None else scope
    got = observation["dimensions"]
    for key in COMPARABILITY:
        if key == "region" and scope["region_requested"]:
            if not scope["region"].intersection(got.get(key, [])):
                return False
        elif key == "sector" and scope["sector_requested"]:
            if not scope["sector"].intersection(got.get(key, [])):
                return False
        elif wanted[key] and wanted[key].isdisjoint(got.get(key, [])):
            return False
    return True


def divergence_candidates(observations, limit=100):
    grouped = defaultdict(list)
    for obs in observations:
        dimensions = obs["dimensions"]
        if any(len(dimensions.get(key, [])) != 1 for key in ("indicator", "region", "period", "unit", "kind")):
            continue
        if any(len(dimensions.get(key, [])) > 1 for key in COMPARABILITY):
            continue
        # Fontes diferentes podem divergir; sinalizar sem presumir metodologia igual.
        signature = tuple(tuple(dimensions.get(key, [])) for key in COMPARABILITY if key != "source")
        grouped[signature].append(obs)
    output = []
    for group in grouped.values():
        values = defaultdict(list)
        for obs in group:
            try:
                values[literal_decimal(obs["value"])].append(obs)
            except (ValueError, InvalidOperation):
                continue
        # Escala entra na assinatura; não comparar 100 mil e 100 milhões.
        if len(values) < 2:
            continue
        shared_dimensions = {key: dimension_values for key, dimension_values in group[0]["dimensions"].items() if key != "source"}
        output.append({"dimensions": shared_dimensions, "status": "requires_review",
                       "reason": "different_values_same_recognized_dimensions",
                       "alternatives": [{"normalized_value": format(value, "f"), "observations": [
                           {"id": obs["id"], "value": obs["value"], "provenance": obs["provenance"], "statistical_sources": obs["dimensions"].get("source", []),
                            "publication_periods": obs.get("publication_periods", [])} for obs in alternatives[:4]],
                                            "observation_count": len(alternatives), "observations_truncated": len(alternatives) > 4}
                                        for value, alternatives in list(values.items())[:8]],
                       "alternatives_count": len(values),
                       "alternatives_truncated": len(values) > 8,
                       "possible_explanations": ["revisão estatística", "metodologias não identificadas", "erro de extração"]})
        if len(output) >= limit:
            break
    return output


def comparison_graph(calculations, observations):
    """Grafo por resposta: derivação não é incorporada ao corpus factual."""
    by_id = {obs["id"]: obs for obs in observations}
    nodes, edges = {}, []
    for trace in calculations:
        identity = json.dumps(trace, sort_keys=True, ensure_ascii=False)
        comparison_id = "comparison:" + hashlib.sha256(identity.encode()).hexdigest()[:24]
        nodes[comparison_id] = {"id": comparison_id, "type": "Comparacao", "operation": trace["operation"],
                                "formula": trace["formula"], "result": trace["result"],
                                "semantic_status": "requires_review", "arithmetic_verified": trace.get("arithmetic_verified", False)}
        for position, operand in enumerate(trace.get("operands", [])):
            operand_id = comparison_id + f":operand:{position}"
            nodes[operand_id] = {"id": operand_id, "type": "OperandoCalculo", "value": operand["value"],
                                "dimensions": operand.get("dimensions", {}), "sources": operand.get("sources", [])}
            role = "BASE_DE" if position == 0 else "FINAL_DE" if position == 1 else "OPERANDO_DE"
            if trace["operation"] in {"sum", "mean"}:
                role = "OPERANDO_DE"
            edges.append({"source": operand_id, "relation": role, "target": comparison_id})
            for obs_id in operand.get("observation_candidates", []):
                if obs_id in by_id:
                    nodes[obs_id] = {"id": obs_id, "type": "ObservacaoEstatistica", "value": by_id[obs_id]["value"],
                                     "dimensions": by_id[obs_id]["dimensions"], "provenance": by_id[obs_id]["provenance"]}
                    edges.append({"source": operand_id, "relation": "BASEADO_EM", "target": obs_id})
            for source in operand.get("sources", []):
                chunk = source.get("node_id")
                if chunk:
                    nodes[chunk] = {"id": chunk, "type": "Chunk", "file": source.get("file"), "page": source.get("page")}
                    edges.append({"source": operand_id, "relation": "SUSTENTADA_POR", "target": chunk})
    unique_edges = {json.dumps(edge, sort_keys=True): edge for edge in edges}
    return {"scope": "query_only", "nodes": list(nodes.values()), "relations": list(unique_edges.values()), "persisted_as_fact": False}


class CorpusKnowledge:
    def __init__(self, nodes):
        self.observations = tuple({obs["id"]: obs for node in nodes for obs in node_observations(node)}.values())
        self._nodes_count = len(nodes)
        self.available_regions = {region for obs in self.observations for region in obs["dimensions"].get("region", [])}

    def report(self, question=""):
        wanted, scope = facets(question), hierarchy_scope(question)
        observations = [obs for obs in self.observations if not question or observation_matches(obs, wanted=wanted, scope=scope)]
        dimensions = {key: dict(sorted(Counter(value for obs in observations for value in obs["dimensions"].get(key, [])).items()))
                      for key in COMPARABILITY}
        combinations_available = Counter()
        for obs in observations:
            keys = ("indicator", "region", "period", "unit", "sector")
            if any(len(obs["dimensions"].get(key, [])) != 1 for key in keys[:4]) or len(obs["dimensions"].get("sector", [])) > 1:
                continue
            combinations_available[tuple((obs["dimensions"].get(key) or [""])[0] for key in keys)] += 1
        available = [{**dict(zip(("indicator", "region", "period", "unit", "sector"), values)), "candidate_count": count}
                     for values, count in sorted(combinations_available.items())[:200]]
        expected_regions = scope["region"] if scope["region_requested"] else wanted["region"]
        expected_sectors = scope["sector"] if scope["sector_requested"] else wanted["sector"]
        gaps = []
        combinations = itertools.product(wanted["indicator"] or [None], expected_regions or [None], wanted["period"] or [None], expected_sectors or [None])
        for indicator, region, period, sector in itertools.islice(combinations, 100):
            combination = {key: value for key, value in zip(("indicator", "region", "period", "sector"), (indicator, region, period, sector)) if value}
            if combination and not any(all(value in obs["dimensions"].get(key, []) for key, value in combination.items()) for obs in observations):
                gaps.append(combination)
        conflicts = divergence_candidates(observations)
        requested_count = len(wanted["indicator"] or [None]) * len(expected_regions or [None]) * len(wanted["period"] or [None]) * len(expected_sectors or [None])
        return deepcopy({"scope": "indexed_corpus", "indexed_nodes": self._nodes_count,
                         "total_candidates": len(self.observations), "matched_candidates": len(observations),
                         "requested_dimensions": {key: sorted(values) for key, values in wanted.items()},
                         "dimensions": dimensions, "candidate_status": dict(Counter(obs["status"] for obs in observations)),
                         "available_combinations": available, "available_combinations_total": len(combinations_available),
                         "available_combinations_truncated": len(combinations_available) > 200,
                         "missing_requested_combinations": gaps, "gap_limit": 100,
                         "requested_combinations_may_be_truncated": requested_count > 100,
                         "divergences": conflicts, "divergences_limit": 100, "divergences_may_be_truncated": len(conflicts) >= 100,
                         "hierarchy": {key: sorted(value) if isinstance(value, set) else value for key, value in scope.items()},
                         "registry_limits": {"territories": len(TERRITORIES), "municipalities": sum(d["type"] == "Municipio" for d in TERRITORIES.values()), "sector_edges": len(SECTOR_PARENTS)},
                         "automatic_aggregation": False, "requires_review": True,
                         "meaning": "Cobertura de candidatos indexados; ausência não prova inexistência do dado."})
