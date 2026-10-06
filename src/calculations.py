"""Planos JSON limitados: o modelo seleciona células; Python calcula com Decimal."""
from decimal import Decimal, InvalidOperation, localcontext, ROUND_HALF_UP
import json
import re

from numerical_validator import _NUM_RE, _normalize
from structured_output import parse_json_object, StructuredOutputError
from evidence import facets
from domain_ontology import comparison_issues, node_observations, prompt_block
from statistical_observations import numeric_literal, DATE_LABEL
from knowledge_analytics import hierarchy_scope

_PLAN = """Selecione uma operação e as células dos dados que respondem à pergunta.
Não calcule valores e não invente operandos. Retorne apenas JSON:
{{"operation":"difference|percent_change|percentage_points|sum|mean|none",
"operands":[{{"row":0,"column":"nome exato"}}]}}
Índices de linha começam em zero. Para diferença/variação: primeiro base,
depois valor final. Use none se a operação ou as unidades forem ambíguas.
Dados (JSON): {data}
Pergunta: {question}
"""


def _decimal(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("Operando não numérico")
    raw = str(value).strip()
    if isinstance(value, str):
        if not re.fullmatch(r"[-−]?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?\s*%?", raw):
            raise ValueError("Formato numérico ambíguo")
        raw = _normalize(raw)
    result = Decimal(raw)
    if not result.is_finite() or abs(result) > Decimal("1e30"):
        raise ValueError("Operando fora dos limites")
    return result


def _format(value):
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f").replace(".", ",")


def _operand_text(value):
    return format(value, "f").replace(".", ",")


def calculate(question, df, data, llm, nodes):
    """Devolve contexto e trilha; ausência de evidência impede a operação."""
    if df is not None:
        rows = df.astype(object).where(df.notna(), None).head(100).to_dict(orient="records")
    elif data is not None and all(not isinstance(v, list) for v in data.values()):
        rows = [{"Indicador": key, "Valor": value} for key, value in data.items()]
    else:
        return json.dumps(data, ensure_ascii=False), []
    preview = json.dumps(rows, ensure_ascii=False)
    if not rows:
        return "[Sem dados estruturados]", []
    try:
        plan = parse_json_object(llm.complete(prompt_block(question) + _PLAN.format(data=preview, question=question)).text)
        operation = plan.get("operation")
        if operation == "none":
            return preview, []
        if operation not in {"difference", "percent_change", "percentage_points", "sum", "mean"}:
            raise ValueError("Operação não permitida")
        refs = plan.get("operands")
        if not isinstance(refs, list) or not 1 <= len(refs) <= 100:
            raise ValueError("Operandos inválidos")
        if operation in {"difference", "percent_change", "percentage_points"} and len(refs) != 2:
            raise ValueError("Operação exige dois operandos")
        values, evidence, seen = [], [], set()
        observations = [obs for node in nodes for obs in node_observations(node)]
        for ref in refs:
            row_index, column = ref["row"], ref["column"]
            if type(row_index) is not int or not 0 <= row_index < len(rows):
                raise ValueError("Linha inválida")
            if (row_index, column) in seen:
                raise ValueError("Célula repetida")
            seen.add((row_index, column))
            value = _decimal(rows[row_index][column])
            label = " | ".join(str(v) for key, v in rows[row_index].items() if key != column
                               and (DATE_LABEL.search(str(key)) or not numeric_literal(v)))
            cell_dimensions = facets(column + " " + label + " " + str(rows[row_index][column]))
            matches = []
            for node in nodes:
                inner = getattr(node, "node", node)
                text = getattr(inner, "text", "") or node.get_content()
                for match in _NUM_RE.finditer(text):
                    if Decimal(_normalize(match.group(1))) == value:
                        # Apenas aponta a ocorrência original, sem tratar a
                        # seleção de célula pelo LLM como validação semântica.
                        matches.append({
                            "node_id": str(getattr(getattr(node, "node", node), "node_id", "")),
                            "file": str((getattr(node, "metadata", {}) or {}).get("source_file", "")),
                            "page": (getattr(node, "metadata", {}) or {}).get("page"),
                            "excerpt": text[max(0, match.start()-140):match.end()+140],
                        })
            if not matches:
                raise ValueError("Operando ausente das fontes")
            candidates = [obs for obs in observations if _decimal(obs["value"]) == value
                          and any(source["node_id"] == obs["provenance"]["node_id"] for source in matches)
                          and all(not expected or expected.issubset(set(obs["dimensions"].get(key, [])))
                                  for key, expected in cell_dimensions.items())]
            signatures = {json.dumps(obs["dimensions"], sort_keys=True) for obs in candidates}
            # Cabeçalhos anuais podem ocupar colunas diferentes; a compatibilidade vem das dimensões.
            if candidates and len(signatures) == 1:
                cell_dimensions = {key: set(items) for key, items in candidates[0]["dimensions"].items()}
                matches = [{"node_id": obs["provenance"]["node_id"], "file": obs["provenance"]["file"],
                            "page": obs["provenance"]["page"], "excerpt": obs["provenance"]["excerpt"],
                            "observation_id": obs["id"], "bound_dimensions": obs["dimensions"],
                            "cell_provenance": obs["provenance"], "observation_status": obs["status"]} for obs in candidates]
            values.append(value)
            evidence.append({"row": row_index, "column": column, "label": label,
                             "value": str(value), "sources": matches,
                             "dimensions": {key: sorted(items) for key, items in cell_dimensions.items()}})
        dimensions = [{key: set(items) for key, items in item["dimensions"].items()} for item in evidence]
        wanted = facets(question)
        scope = hierarchy_scope(question)
        for key in ("indicator", "region", "unit", "scale", "sector", "source", "basis", "coverage"):
            expected = scope[key] if scope.get(key + "_requested") else wanted[key]
            if expected and any(not d[key] or d[key].isdisjoint(expected) for d in dimensions):
                raise ValueError("Operando fora do recorte solicitado")
        semantic_issues = comparison_issues(dimensions, operation)
        if semantic_issues:
            return preview + "\n[Cálculo não realizado: " + "; ".join(semantic_issues) + "]", []
        for operand, dimensions_for_operand in zip(evidence, dimensions):
            operand["dimensions"] = {k: sorted(v) for k, v in dimensions_for_operand.items()}
            # Exige apoio contextual nos operandos, além da presença do valor.
            from evidence import contextual_support
            operand_claim = operand["column"] + " " + operand["label"] + " " + str(rows[operand["row"]][operand["column"]])
            contextual_sources = [source for source in operand["sources"]
                                  if source.get("bound_dimensions") == operand["dimensions"]
                                  or contextual_support(operand_claim, source["excerpt"])[0]]
            if not contextual_sources:
                return preview + "\n[Cálculo não realizado: operando sem apoio contextual na fonte]", []
            operand["sources"] = contextual_sources[:5]
            operand["observation_candidates"] = [
                obs["id"] for obs in observations
                if any(source["node_id"] == obs["provenance"]["node_id"] for source in operand["sources"])
                and _decimal(obs["value"]) == Decimal(operand["value"])
                and obs["dimensions"] == operand["dimensions"]
            ]
        if not dimensions[0]["unit"] or any(d["unit"] != dimensions[0]["unit"] for d in dimensions):
            raise ValueError("Unidades não explícitas ou incompatíveis")
        if any(d["indicator"] != dimensions[0]["indicator"] or d["region"] != dimensions[0]["region"] for d in dimensions):
            raise ValueError("Indicadores ou regiões diferentes exigem revisão")
        if operation == "percentage_points" and dimensions[0]["unit"] != {"percentual"}:
            raise ValueError("Pontos percentuais exigem valores percentuais explícitos")
        with localcontext() as ctx:
            ctx.prec = 50
            if operation in {"difference", "percentage_points"}:
                result = values[1] - values[0]
                formula = f"{_operand_text(values[1])} - {_operand_text(values[0])}"
            elif operation == "percent_change":
                if values[0] <= 0:
                    raise ValueError("Variação percentual exige base positiva")
                result = (values[1] - values[0]) / values[0] * 100
                formula = f"({_operand_text(values[1])} - {_operand_text(values[0])}) / {_operand_text(values[0])} * 100"
            else:
                result = sum(values)
                formula = " + ".join(_operand_text(v) for v in values)
                if operation == "mean":
                    result /= len(values)
                    formula = f"({formula}) / {len(values)}"
            formatted = _format(result)
        suffix = " p.p." if operation == "percentage_points" else " %" if operation == "percent_change" else ""
        trace = {"operation": operation, "operands": evidence, "formula": formula,
                 "result": formatted + suffix, "arithmetic_verified": True,
                 "semantic_status": "requires_review", "rounding": "ROUND_HALF_UP", "decimal_places": 2}
        return preview + "\n[Cálculo Python; conferir seleção dos operandos]\n" + json.dumps(trace, ensure_ascii=False), [trace]
    except (StructuredOutputError, ValueError, KeyError, TypeError, InvalidOperation, ZeroDivisionError):
        return preview + "\n[Cálculo não realizado: operação ou evidência insuficiente]", []
