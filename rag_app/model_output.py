"""Distingue falhas de geração de respostas sem evidência documental."""
import asyncio
import json
import re


class EmptyModelResponse(RuntimeError):
    """O provedor concluiu a chamada sem produzir texto utilizável."""


class InvalidModelResponse(EmptyModelResponse):
    """Texto foi produzido, mas contém sinais explícitos de saída inválida."""


def quality_issues(text: str) -> list[str]:
    issues = []
    if re.fullmatch(r'\s*(?:(?:user|assistant)\s+safety\s*:\s*)?(?:safe|unsafe)\s*[.!]?\s*', text, re.I):
        issues.append('rótulo de classificação em lugar de resposta')
    if '\ufffd' in text or any(0xD800 <= ord(c) <= 0xDFFF for c in text):
        issues.append('caracteres corrompidos')
    # Código/JSON e citações literais podem conter nomes e termos estrangeiros.
    prose = re.sub(r'```[\s\S]*?```|`[^`]*`|"[^"\n]*"|“[^”]*”', '', text)
    try:
        structured = isinstance(json.loads(text), (dict, list))
    except (ValueError, TypeError):
        structured = False
    if not structured:
        words = re.findall(r'[a-zá-ú]+', prose.casefold())
        pt = sum(w in {'de','da','do','dos','das','em','com','para','não','são','foi','uma','que','entre'} for w in words)
        english = sum(w in {'while','however','therefore','according','were','these','those','because','the','and','with','this'} for w in words)
        if pt >= 3 and (re.search(r'[\u3400-\u9fff\u3040-\u30ff\u0400-\u04ff]', prose) or english >= 3 and english / max(1,len(words)) >= .08):
            issues.append('mistura de idiomas na resposta em português')
    return issues


def response_text(response) -> str:
    text = getattr(response, "text", None)
    if not isinstance(text, str) or not text.strip():
        raise EmptyModelResponse(
            "O modelo retornou uma resposta vazia. Isso não significa ausência de dados. "
            "Tente novamente e confira o provedor configurado se o problema persistir."
        )
    issues = quality_issues(text)
    if issues:
        raise InvalidModelResponse('O modelo produziu texto inadequado: ' + '; '.join(issues) + '. Confira o provedor se persistir.')
    return text


async def acomplete(llm, prompt):
    """Prefere I/O cancelável; mantém compatibilidade com LLMs síncronos."""
    method = getattr(llm, "acomplete", None)
    if callable(method):
        return await method(prompt)
    return await asyncio.to_thread(llm.complete, prompt)
