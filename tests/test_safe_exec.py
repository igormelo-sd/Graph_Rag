"""
Testes de segurança do safe_exec.

Cobrem: o caminho feliz (código pandas legítimo), os bloqueios (import, dunder,
builtins perigosos) e o watchdog de timeout. Rode a partir de rag_principal/:

    cd rag_principal && python -m pytest tests/test_safe_exec.py -q
"""
import time

import pandas as pd
import pytest

from safe_exec import safe_exec, SafeExecTimeout


# ── Caminho feliz ─────────────────────────────────────────────────────────────

def test_codigo_pandas_legitimo_atualiza_namespace():
    df = pd.DataFrame({"pib": [1.0, 2.0, 3.0]})
    ns = {"pd": pd, "df": df}
    safe_exec("resultado = df['pib'].sum()", ns)
    assert ns["resultado"] == 6.0


def test_pd_injetado_dispensa_import():
    ns = {"pd": pd, "df": pd.DataFrame({"x": [1, 2]})}
    safe_exec("resultado = pd.concat([df, df])['x'].max()", ns)
    assert ns["resultado"] == 2


# ── Bloqueios de import (todos, inclusive pandas — pd já é injetado) ──────────

@pytest.mark.parametrize("code", [
    "import os",
    "import subprocess",
    "from os import system",
    "import pandas",
    "import pandas as pd",
])
def test_import_proibido_bloqueado(code):
    with pytest.raises(ValueError):
        safe_exec(code, {"pd": pd})


# ── Escape clássico via atributos dunder ──────────────────────────────────────

@pytest.mark.parametrize("code", [
    "x = ().__class__.__mro__[1].__subclasses__()",
    "x = ().__class__",
    "x = [].__class__.__base__",
    "x = (1).__class__.__bases__",
    "x = type(df).__init__.__globals__",
])
def test_escape_dunder_bloqueado(code):
    with pytest.raises(ValueError):
        safe_exec(code, {"pd": pd, "df": pd.DataFrame({"a": [1]})})


# ── Builtins perigosos indisponíveis ──────────────────────────────────────────

@pytest.mark.parametrize("code", [
    "x = open('x.txt')",
    "x = eval('1+1')",
    "x = exec('y=1')",
    "x = __import__('os')",
    "x = getattr(df, 'to_csv')",
    "x = globals()",
])
def test_builtin_perigoso_indisponivel(code):
    # NameError vira RuntimeError na camada de execução do safe_exec.
    with pytest.raises((RuntimeError, ValueError)):
        safe_exec(code, {"pd": pd, "df": pd.DataFrame({"a": [1]})})


# ── Superfície pandas: I/O e acesso indireto ao sistema ───────────────────────

@pytest.mark.parametrize("code", [
    "x = pd.read_csv('/etc/passwd')",
    "x = pd.read_pickle('payload.pkl')",
    "df.to_csv('saida.csv')",
    "df.to_pickle('saida.pkl')",
    "x = pd.io.common.os.system('id')",
    "x = df.plot()",
])
def test_io_e_atributos_pandas_perigosos_bloqueados(code):
    with pytest.raises(ValueError):
        safe_exec(code, {"pd": pd, "df": pd.DataFrame({"a": [1]})})


@pytest.mark.parametrize("code", [
    "def f():\n    return 1",
    "class X:\n    pass",
    "x = lambda value: value",
])
def test_definicoes_dinamicas_bloqueadas(code):
    with pytest.raises(ValueError):
        safe_exec(code, {"pd": pd})


# ── Watchdog de timeout ───────────────────────────────────────────────────────

def test_loop_infinito_abortado_por_timeout():
    t0 = time.monotonic()
    with pytest.raises(SafeExecTimeout):
        safe_exec("while True:\n    pass", {"pd": pd}, timeout_s=0.5)
    # Não pode ter travado muito além do limite.
    assert time.monotonic() - t0 < 3.0


# ── Sintaxe inválida ──────────────────────────────────────────────────────────

def test_sintaxe_invalida_vira_valueerror():
    with pytest.raises(ValueError):
        safe_exec("resultado = = 1", {"pd": pd})
