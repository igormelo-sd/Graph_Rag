"""Distingue falhas de geração de respostas sem evidência documental."""
import asyncio


class EmptyModelResponse(RuntimeError):
    """O provedor concluiu a chamada sem produzir texto utilizável."""


def response_text(response) -> str:
    text = getattr(response, "text", None)
    if not isinstance(text, str) or not text.strip():
        raise EmptyModelResponse(
            "O modelo retornou uma resposta vazia. Isso não significa ausência de dados. "
            "Tente novamente e confira o provedor configurado se o problema persistir."
        )
    return text


async def acomplete(llm, prompt):
    """Prefere I/O cancelável; mantém compatibilidade com LLMs síncronos."""
    method = getattr(llm, "acomplete", None)
    if callable(method):
        return await method(prompt)
    return await asyncio.to_thread(llm.complete, prompt)
