"""Qualificadores conservadores do trecho: não inferir causalidade ou confiança numérica."""
import json
import re
from domain_ontology import fold, periods


def relation_attributes(relation, evidence, metadata, node_id):
    from statistical_observations import reference_text, publication_periods
    text = fold(evidence)
    polarity_text = re.sub(r"\bnao\s+(?:so|apenas|somente)\b", "", text)
    if re.search(r"\b(?:nao|nunca|jamais)\b|\bsem\s+(?:crescimento|aumento|reducao|queda|correlacao|associacao|efeito|impacto)\b", polarity_text):
        raise ValueError("Negação no trecho: relação positiva não inserida")
    causal = bool(re.search(r"\b(?:causou|causa|causar|provocou|provoca|provocar|levou a|resultou em|em decorrencia de|devido a)\b", text))
    association = bool(re.search(r"\b(?:correlacao|associacao|associad[oa]s?|correlacionad[oa]s?)\b", text))
    if relation == "CAUSA" and (not causal or association):
        raise ValueError("Causalidade sem afirmação causal literal inequívoca")
    if relation == "ASSOCIADO_A" and not association:
        raise ValueError("Associação sem marcador literal")
    if relation == "CRESCEU_EM" and not re.search(r"\b(?:cresceu|crescimento|aumentou|aumento|avancou|alta)\b", text):
        raise ValueError("Crescimento sem marcador literal")
    if relation == "RECUOU_EM" and not re.search(r"\b(?:recuou|recuo|diminuiu|queda|caiu|reducao)\b", text):
        raise ValueError("Recuo sem marcador literal")
    modality = "uncertain" if re.search(r"\b(?:pode|podem|poderia|talvez|possivel|provavel|estima|estimado|projecao)\b", text) else "asserted"
    if re.search(r"(?<![-\w])se\b|\bcaso\b", text):
        modality = "conditional"
    relation_kind = "causal_claim" if relation == "CAUSA" else "association" if relation in {"ASSOCIADO_A", "RELACIONA_COM"} else "typed_relation"
    return {"evidence": evidence, "polarity": "affirmed", "modality": modality, "relation_kind": relation_kind,
            "validity_periods_json": json.dumps(sorted(periods(reference_text(evidence)))),
            "publication_periods_json": json.dumps(publication_periods(evidence)),
            "source_file": str(metadata.get("source_file", "")), "page": str(metadata.get("page", "")),
            "source_node_id": node_id, "method": "llm_literal_and_type_checks",
            "review_status": "pending", "semantic_status": "requires_review", "confidence_method": "not_scored",
            "literal_assertion": modality == "asserted"}
