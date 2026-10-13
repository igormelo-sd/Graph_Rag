"""Resolve a implementação explicitamente, sem depender do diretório corrente."""
import sys
from pathlib import Path


def activate(base_dir: Path) -> None:
    """Mantém imports legados locais e impede mistura silenciosa das variantes."""
    base_dir = base_dir.resolve()
    source = base_dir / "src"
    for file in source.glob("*.py"):
        loaded = sys.modules.get(file.stem)
        origin = getattr(loaded, "__file__", None)
        if origin and Path(origin).resolve() != file.resolve():
            raise RuntimeError(
                f"Módulo {file.stem} já carregado de outra origem: {origin}. "
                "Execute cada variante em um processo separado."
            )
    # A pasta src deve vir primeiro, inclusive sobre a raiz do repositório.
    for directory in (base_dir, source):
        value = str(directory)
        if value in sys.path:
            sys.path.remove(value)
        sys.path.insert(0, value)


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure) and getattr(stream, "encoding", None) != "utf-8":
            reconfigure(encoding="utf-8")
