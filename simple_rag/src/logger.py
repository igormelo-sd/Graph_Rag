"""
logger — configuração central de logging para o RAG Estatístico SP.

Variáveis de ambiente:
    LOG_LEVEL   : nível mínimo de log (padrão: INFO)
    LOG_FORMAT  : "text" (padrão, legível) ou "json" (produção, estruturado)

Uso nos módulos:
    from logger import get_logger
    log = get_logger(__name__)
    log.info("mensagem")
    log.warning("aviso", extra={"question": "...", "latency_ms": 42})
"""
import json
import logging
import os
from datetime import datetime, timezone

_SETUP_DONE = False

_TEXT_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s — %(message)s"
_DATE_FORMAT = "%H:%M:%S"

# Campos extras reconhecidos pelo JsonFormatter
_EXTRA_FIELDS = (
    "request_id", "question", "sources", "latency_ms",
    "chunks", "fallback", "event",
)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        for field in _EXTRA_FIELDS:
            if hasattr(record, field):
                entry[field] = getattr(record, field)
        return json.dumps(entry, ensure_ascii=False)


def setup_logging() -> None:
    """
    Configura o handler raiz. Idempotente — pode ser chamado mais de uma vez
    sem duplicar handlers.
    """
    global _SETUP_DONE
    if _SETUP_DONE:
        return

    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    fmt = os.getenv("LOG_FORMAT", "text").lower()

    handler = logging.StreamHandler()
    if fmt == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(_TEXT_FORMAT, datefmt=_DATE_FORMAT))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Silencia loggers verbosos de bibliotecas externas
    for noisy in ("httpx", "httpcore", "chromadb", "llama_index", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _SETUP_DONE = True


def get_logger(name: str) -> logging.Logger:
    """Retorna logger nomeado. setup_logging() é chamado automaticamente."""
    setup_logging()
    return logging.getLogger(name)
