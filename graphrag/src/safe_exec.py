"""
safe_exec — helper legado para execução restrita de expressões pandas.

Três camadas de proteção:
  1. AST — bloqueia **qualquer import** (o namespace já injeta ``pd``/``df``) e
     **qualquer acesso a atributo dunder** (``obj.__class__``,
     ``().__subclasses__``…), fechando o escape clássico de sandbox que alcança
     ``os``/``builtins`` sem import.
  2. Builtins — substitui ``__builtins__`` por whitelist explícita: sem
     ``__import__``, ``open``, ``exec``, ``eval``, ``compile``, ``getattr`` ou
     acesso ao sistema.
  3. Watchdog de tempo — um tracer por linha aborta a execução se ela exceder
     ``timeout_s``, interrompendo laços infinitos (``while True``) que o LLM
     possa gerar. Funciona em qualquer plataforma (não usa ``signal``).

O fluxo RAG não executa mais Python gerado por LLM. Este helper permanece por
compatibilidade com consumidores locais e aplica uma allowlist conservadora de
atributos. Ele não deve ser tratado como substituto de isolamento de processo.
"""
import ast
import sys
import time

from logger import get_logger

log = get_logger(__name__)

# Apenas funções seguras da stdlib, suficientes para código pandas + formatação
_SAFE_BUILTINS: dict = {
    # Tipos primitivos
    "bool": bool, "int": int, "float": float, "str": str,
    "list": list, "dict": dict, "tuple": tuple, "set": set,
    # Aritmética e comparação
    "abs": abs, "round": round, "sum": sum, "min": min, "max": max,
    # Iteração
    "len": len, "range": range, "enumerate": enumerate,
    "zip": zip, "sorted": sorted, "reversed": reversed,
    # Strings e formatação
    "format": format,
    # Inspeção de tipo limitada
    "isinstance": isinstance,
    # print bloqueado silenciosamente (LLM às vezes gera, não deve causar erro)
    "print": lambda *a, **kw: None,
}

_FORBIDDEN = (ast.Import, ast.ImportFrom)

_FORBIDDEN_STATEMENTS = (
    ast.AsyncFunctionDef, ast.AsyncWith, ast.Await, ast.ClassDef,
    ast.Delete, ast.FunctionDef, ast.Global, ast.Lambda, ast.Nonlocal,
    ast.Raise, ast.Try, ast.With, ast.Yield, ast.YieldFrom,
)

# A allowlist é global de propósito: qualquer atributo fora dela é rejeitado,
# independentemente do objeto usado como base. Isso bloqueia pd.read_*, df.to_*,
# pd.io e outros caminhos de I/O/introspecção sem depender do nome da variável.
_SAFE_ATTRIBUTES = {
    # pandas: construção e conversão puramente em memória
    "DataFrame", "Series", "Timestamp", "NA", "concat", "isna", "notna",
    "to_numeric",
    # propriedades/indexadores
    "at", "columns", "dtypes", "dt", "empty", "iat", "iloc", "index",
    "loc", "name", "ndim", "shape", "size", "str", "T", "values",
    # agregações e transformações sem I/O
    "abs", "agg", "aggregate", "all", "any", "astype", "count", "cummax",
    "cummin", "cumprod", "cumsum", "diff", "drop_duplicates", "dropna",
    "fillna", "first", "groupby", "idxmax", "idxmin", "item", "last",
    "max", "mean", "median", "min", "mode", "nunique", "pct_change",
    "prod", "quantile", "rank", "rename", "replace", "reset_index", "round",
    "shift", "sort_index", "sort_values", "std", "sum", "to_dict", "unique",
    "value_counts", "var",
    # operações de string via Series.str
    "contains", "endswith", "lower", "startswith", "strip", "upper",
}

MAX_CODE_CHARS = 20_000
MAX_AST_NODES = 2_000

# Tempo máximo de execução do código gerado (segundos).
DEFAULT_TIMEOUT_S = 5.0


class SafeExecTimeout(RuntimeError):
    """Execução excedeu o tempo máximo permitido."""


def _validate_ast(tree: ast.AST) -> None:
    """Camada 1 — rejeita imports não aprovados e acesso a atributos dunder."""
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_AST_NODES:
        raise ValueError("Código gerado acima do limite de complexidade.")

    for node in nodes:
        # Imports — proibidos por completo (o namespace já injeta pd/df).
        if isinstance(node, _FORBIDDEN):
            stmt = ast.unparse(node) if hasattr(ast, "unparse") else ast.dump(node)
            log.warning(
                "Codigo gerado pelo LLM bloqueado por import proibido: '%s'", stmt,
                extra={"event": "safe_exec_blocked"},
            )
            raise ValueError(f"Import não permitido no código gerado: '{stmt}'")

        if isinstance(node, _FORBIDDEN_STATEMENTS):
            raise ValueError(
                f"Construção Python não permitida: '{type(node).__name__}'"
            )

        # Acesso a atributo dunder — fecha o escape via __class__/__subclasses__/…
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            log.warning(
                "Codigo gerado pelo LLM bloqueado por atributo dunder: '.%s'",
                node.attr, extra={"event": "safe_exec_blocked"},
            )
            raise ValueError(
                f"Acesso a atributo interno não permitido: '.{node.attr}'"
            )

        if isinstance(node, ast.Attribute) and node.attr not in _SAFE_ATTRIBUTES:
            log.warning(
                "Codigo gerado bloqueado por atributo fora da allowlist: '.%s'",
                node.attr, extra={"event": "safe_exec_blocked"},
            )
            raise ValueError(f"Atributo não permitido: '.{node.attr}'")


def safe_exec(code: str, ns: dict, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
    """
    Executa `code` com namespace restrito, builtins whitelistados e limite de tempo.

    Parâmetros
    ----------
    code : str
        Código Python gerado pelo LLM.
    ns : dict
        Namespace de entrada (ex: {"pd": pd, "df": df}).
        Atualizado in-place com as variáveis definidas pelo código.
    timeout_s : float
        Tempo máximo de execução antes de abortar (default 5 s).

    Raises
    ------
    ValueError
        Se o código contiver imports/atributos proibidos ou sintaxe inválida.
    SafeExecTimeout
        Se a execução exceder `timeout_s`.
    RuntimeError
        Se a execução lançar qualquer outra exceção.
    """
    if not isinstance(code, str) or len(code) > MAX_CODE_CHARS:
        raise ValueError("Código ausente ou acima do limite permitido.")

    # Camada 1 — validação AST (antes de qualquer execução)
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"Sintaxe inválida no código gerado: {exc}") from exc

    _validate_ast(tree)

    # Camada 3 — watchdog de tempo via tracer por linha.
    deadline = time.monotonic() + timeout_s

    def _tracer(frame, event, arg):
        if time.monotonic() > deadline:
            raise SafeExecTimeout(
                f"Execução excedeu o limite de {timeout_s:.0f}s (possível loop)."
            )
        return _tracer

    # Camada 2 — execução com builtins restritos
    exec_ns = {"__builtins__": _SAFE_BUILTINS, **ns}
    previous = sys.gettrace()
    sys.settrace(_tracer)
    try:
        exec(code, exec_ns)  # noqa: S102
    except SafeExecTimeout:
        log.warning(
            "Codigo gerado pelo LLM abortado por timeout",
            extra={"event": "safe_exec_timeout"},
        )
        raise
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        sys.settrace(previous)

    # Propaga variáveis definidas pelo código de volta para ns
    ns.update({
        k: v
        for k, v in exec_ns.items()
        if k != "__builtins__" and not k.startswith("__")
    })
