from answer_policy import (
    REFUSAL_TEXT,
    asks_for_sources,
    sanitize_answer,
)


def test_remove_citacao_inline_sem_perder_conteudo():
    answer = (
        "O setor de serviços liderou o crescimento "
        "(Fonte: Boletim_Conjuntura_2024.pdf, p. 18)."
    )
    assert sanitize_answer(answer, question="Qual setor liderou?") == (
        "O setor de serviços liderou o crescimento."
    )


def test_remove_todos_formatos_inline_proibidos():
    answer = (
        "A indústria avançou (pdf, página 12). "
        "Os serviços cresceram (boletim.pdf, p. 18). "
        "O comércio ficou estável [1]."
    )
    assert sanitize_answer(answer, question="Como evoluíram os setores?") == (
        "A indústria avançou. Os serviços cresceram. O comércio ficou estável."
    )


def test_remove_sentenca_de_fonte_sem_apagar_analise():
    assert sanitize_answer(
        "O PIB avançou. Fonte: boletim.pdf, página 2.",
        question="Como evoluiu o PIB?",
    ) == "O PIB avançou."
    assert sanitize_answer(
        "Fonte: boletim.pdf, página 2. O PIB avançou.",
        question="Como evoluiu o PIB?",
    ) == "O PIB avançou."


def test_remove_bloco_de_fontes_e_metadados():
    answer = """A atividade econômica avançou.

### Fontes
- Boletim_2024.pdf, página 18, score 0,91
- tabela.xlsx, aba 2
"""
    assert sanitize_answer(answer, question="Como evoluiu a atividade?") == (
        "A atividade econômica avançou."
    )


def test_remove_atribuicao_e_nome_de_arquivo():
    answer = (
        "Segundo o documento Boletim_2024.pdf, o emprego cresceu. "
        "A confirmação aparece na página 12."
    )
    cleaned = sanitize_answer(answer, question="Como evoluiu o emprego?")
    assert cleaned == "O emprego cresceu."


def test_remove_detalhes_internos_sem_apagar_recuperacao_economica():
    answer = (
        "A recuperação econômica ganhou força. "
        "Foram usados 8 chunks com score de similaridade elevado. "
        "O nível de atividade avançou."
    )
    assert sanitize_answer(answer, question="Como evoluiu a economia?") == (
        "A recuperação econômica ganhou força. O nível de atividade avançou."
    )


def test_pedido_explicito_preserva_referencia_mas_nao_detalhes_internos():
    question = "Quais foram as fontes?"
    answer = (
        "Fonte: Boletim_2024.pdf, página 18. "
        "O contexto recuperado teve 8 chunks."
    )
    assert asks_for_sources(question)
    assert sanitize_answer(answer, question=question) == (
        "Fonte: Boletim_2024.pdf, página 18."
    )


def test_resposta_vazia_usa_mensagem_padrao():
    assert sanitize_answer("", question="Qual o dado?") == REFUSAL_TEXT


def test_pergunta_generica_sobre_documentos_nao_libera_metadados():
    assert not asks_for_sources("Analise os documentos sobre atividade econômica.")


def test_variantes_de_pedido_explicito_de_fontes():
    assert asks_for_sources("Qual documento afirma isso?")
    assert asks_for_sources("De onde veio essa informação?")
    assert asks_for_sources("Mostre as referências.")
