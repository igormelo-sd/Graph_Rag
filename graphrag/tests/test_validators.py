from types import SimpleNamespace

from citation_validator import validate_citations
from numerical_validator import validate_numbers
from provenance import format_source_context


def _node(text: str, *, file="regional/boletim.pdf", page=3, score=0.9):
    return SimpleNamespace(
        metadata={"source_file": file, "page": page},
        score=score,
        get_content=lambda: text,
    )


def test_citacao_confere_arquivo_e_pagina():
    nodes = [_node("A taxa foi 7,9%.")]
    checks = validate_citations(
        "A taxa foi 7,9% (Fonte: boletim.pdf, p. 3). ", nodes
    )
    assert len(checks) == 1
    assert checks[0].verified


def test_citacao_com_pagina_incorreta_e_rejeitada():
    checks = validate_citations(
        "A taxa foi 7,9% (Fonte: boletim.pdf, p. 9).", [_node("7,9%")]
    )
    assert not checks[0].verified


def test_citacao_normaliza_markdown_e_intervalo_de_paginas():
    nodes = [
        _node("Primeiro trecho.", file="regional/boletim.pdf", page=3),
        _node("Segundo trecho.", file="regional/boletim.pdf", page=4),
    ]
    checks = validate_citations(
        "Síntese (**Fonte:** `boletim.pdf`, p. 3–4).",
        nodes,
    )
    assert len(checks) == 1
    assert checks[0].verified


def test_citacao_rejeita_intervalo_com_pagina_nao_recuperada():
    checks = validate_citations(
        "Síntese (Fonte: boletim.pdf, p. 3–5).",
        [_node("Trecho.", page=3), _node("Trecho.", page=5)],
    )
    assert not checks[0].verified


def test_contexto_enviado_ao_llm_inclui_proveniencia():
    context = format_source_context(_node("Trecho documental."))
    assert "Fonte: regional/boletim.pdf" in context
    assert "p./aba 3" in context
    assert context.endswith("Trecho documental.")


def test_equacao_do_llm_nao_confirma_resultado_sem_trilha():
    checks = validate_numbers(
        "A diferença foi 3,4% − 2,8% = 0,6 p.p.",
        [_node("Taxas observadas: 3,4% e 2,8%.")],
    )
    by_value = {check.value: check for check in checks}
    assert not by_value["0,6"].verified
    assert not by_value["0,6"].value_found


def test_resultado_aritmetico_incorreto_e_rejeitado():
    checks = validate_numbers(
        "A diferença foi 3,4% − 2,8% = 0,9 p.p.",
        [_node("Taxas observadas: 3,4% e 2,8%.")],
    )
    by_value = {check.value: check for check in checks}
    assert not by_value["0,9"].verified


def test_numero_verificado_preserva_posicao_e_fonte_exatas():
    response = "O primeiro indicador foi 12,5%, mas o principal chegou a 18,7%."
    checks = validate_numbers(
        response,
        [
            _node("Série secundária com resultado de 12,5%.", page=2),
            _node("O indicador principal chegou a 18,7%.", page=8),
        ],
    )
    by_value = {check.value: check for check in checks}

    assert by_value["12,5%"].source_index == 0
    assert response[
        by_value["12,5%"].response_start:by_value["12,5%"].response_end
    ] == "12,5%"
    assert by_value["18,7%"].source_index == 1


def test_citacao_tabular_preserva_linha_estruturada_completa():
    table_node = _node(
        "Setor: Indústria\nEmpregos: 125.400\nVariação: 3,2%\nFonte: tabela.pdf",
        page=4,
    )
    table_node.metadata["type"] = "table"
    checks = validate_numbers(
        "A indústria registrou 125.400 empregos.",
        [table_node],
    )

    assert "125.400" in checks[0].source_snippet
    assert checks[0].value_found
    assert not checks[0].verified  # falta período e região explícitos


def test_mesmo_valor_em_afirmacoes_diferentes_e_validado_separadamente():
    source = "A desocupação no Estado de São Paulo foi 7,9% em 2023."
    answer = source + " A desocupação no Brasil foi 7,9% em 2024."
    rates = [c for c in validate_numbers(answer, [_node(source)]) if c.value == "7,9%"]
    assert len(rates) == 2
    assert rates[0].verified
    assert not rates[1].verified
    assert rates[0].response_start != rates[1].response_start
