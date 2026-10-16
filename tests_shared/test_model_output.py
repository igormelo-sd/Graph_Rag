from types import SimpleNamespace

import pytest

from rag_app.model_output import EmptyModelResponse, response_text


@pytest.mark.parametrize("text", [None, "", " \n\t", 42])
def test_empty_or_invalid_output_is_provider_failure(text):
    with pytest.raises(EmptyModelResponse, match="não significa ausência de dados"):
        response_text(SimpleNamespace(text=text))


def test_valid_output_preserved():
    text = "A indústria paulista recuou em dezembro de 2025."
    assert response_text(SimpleNamespace(text=text)) == text
