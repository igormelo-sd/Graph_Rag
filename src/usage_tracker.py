"""
usage_tracker — custo por query e economia local (port kg usage_tracker).

Usa metrics.record_reported_usage já existente mas persiste JSON diário em
{base_dir}/usage_logs/usage_YYYY-MM-DD.json para auditoria. Opt-in via
RAG_USAGE_TRACK=1 (default 1). Sem custo adicional — só contabilidade.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from logger import get_logger

log = get_logger(__name__)

# Pricing fallback (USD por 1M tokens) — kg MODEL_PRICING + Maritaca estimado
_PRICING = {
    "sabia-4": (1.0, 3.0),
    "sabiazinho-4": (0.5, 1.5),
    "sabia-3": (0.8, 2.4),
    "gpt-5-chat-latest": (5.0, 15.0),
    "gpt-5-mini": (0.3, 1.2),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "qwen3:4b-instruct": (0.0, 0.0),  # local
    "qwen2.5vl:7b": (0.0, 0.0),
    "bge-m3": (0.0, 0.0),
    "bge-reranker-v2-m3": (0.0, 0.0),
}

def usage_enabled() -> bool:
    return os.getenv("RAG_USAGE_TRACK", "1").strip().lower() in {"1", "true", "yes", "on"}

def _price_for(model: str) -> tuple[float, float]:
    m = (model or "").lower()
    for k, v in _PRICING.items():
        if k.lower() in m:
            return v
    # fallback env
    try:
        inp = float(os.getenv("RAG_INPUT_COST_PER_MILLION_USD", "0"))
        out = float(os.getenv("RAG_OUTPUT_COST_PER_MILLION_USD", "0"))
        return inp, out
    except Exception:
        return 0.0, 0.0

def log_usage(base_dir: str, model: str, prompt_tokens: int, completion_tokens: int, extra: dict | None = None) -> dict:
    """Registra custo estimado e persiste JSON diário. Retorna dict com custo."""
    if not usage_enabled():
        return {}
    try:
        inp_price, out_price = _price_for(model)
        cost = (prompt_tokens * inp_price + completion_tokens * out_price) / 1_000_000
        # compara com custo local (zero) para economia
        saving = cost  # vs local
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "model": model,
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "cost_usd": round(cost, 6),
            "saving_vs_local": round(saving, 6),
        }
        if extra:
            entry.update(extra)
        log_dir = Path(base_dir) / "usage_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        fname = f"usage_{time.strftime('%Y-%m-%d')}.json"
        path = log_dir / fname
        # append JSON lines
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        log.info("[Usage] %s | %d+%d tok | $%.6f", model, prompt_tokens, completion_tokens, cost)
        return entry
    except Exception as exc:
        log.warning("[Usage] falha (%s)", exc)
        return {}

def track_from_response(base_dir: str, model: str, response, extra: dict | None = None) -> dict:
    """Extrai usage de response OpenAI-compat e loga."""
    try:
        usage = getattr(response, "usage", None)
        if usage is None:
            return {}
        pt = getattr(usage, "prompt_tokens", None) or getattr(usage, "input_tokens", 0) or 0
        ct = getattr(usage, "completion_tokens", None) or getattr(usage, "output_tokens", 0) or 0
        return log_usage(base_dir, model, int(pt), int(ct), extra=extra)
    except Exception:
        return {}
