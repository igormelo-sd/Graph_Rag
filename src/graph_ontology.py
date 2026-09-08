"""
graph_ontology — descoberta dinâmica de tipos de entidade (port do kg-web-platform ontology.py).

Amostra ≤6 chunks estratégicos (índices [0,1,mid-1,mid,-2,-1]) → LLM propõe até 4 tipos
adicionais além dos 9 fixos. Resultado cacheado em graph_store/ontology.json (TTL: muda
quando base muda). Custo: 1 chamada LLM por reindexação; desabilitado por padrão
(RAG_ONTOLOGY_DISCOVER=0) — P2 opt-in local, sem exfiltração além do LLM já usado.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from logger import get_logger

log = get_logger(__name__)

_FIXED_TYPES = {
    "Indicador", "Setor", "Região", "Período", "FonteDados",
    "Tabela", "Grafico", "Pagina", "Documento",
}

_ONTOLOGY_PROMPT = """\
Você é especialista em ontologia econômica para boletins da Fundação SEADE (Estado de SP).

Tipos já existentes (NÃO repita): {fixed}

Amostra de trechos do corpus (até 6):
{sample}

Tarefa: proponha até 4 tipos de entidade ADICIONAIS que aparecem recorrentemente no corpus
e não estão cobertos pelos fixos. Exemplos úteis: Empresa, Município, PolíticaPublica, Produto,
CadeiaProdutiva, ModalLogistico. Evite tipos genéricos (Conceito, Dado, Outro).

Retorne APENAS JSON válido, sem markdown:
{{"entity_types": [{{"name": "Empresa", "description": "empresas citadas"}}, ...]}}
Se nada relevante, retorne {{"entity_types": []}}.
Nome: PascalCase, 3-20 chars, sem acento, sem espaços.
"""

def _ontology_path(base_dir: str) -> Path:
    return Path(base_dir) / "graph_store" / "ontology.json"

def _load_cached(base_dir: str) -> list[str] | None:
    p = _ontology_path(base_dir)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        types = [t.strip() for t in data.get("entity_types", []) if isinstance(t, str) and t.strip()]
        return [t for t in types if t not in _FIXED_TYPES][:4]
    except Exception:
        return None

def _save_cached(base_dir: str, types: list[str], raw: dict | None = None) -> None:
    p = _ontology_path(base_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"entity_types": types}
    if raw:
        payload["_raw"] = raw
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def _sample_chunks(nodes: list, k: int = 6) -> list:
    if not nodes:
        return []
    # filtra só texto narrativo, como graph_indexing faz
    text_nodes = [n for n in nodes if getattr(n, "metadata", {}).get("type", "text") == "text"]
    pool = text_nodes or nodes
    n = len(pool)
    if n <= k:
        idx = list(range(n))
    else:
        mid = n // 2
        idx = [0, 1, mid - 1, mid, n - 2, n - 1]
        # dedup preservando ordem
        seen = set()
        idx = [i for i in idx if not (i in seen or seen.add(i))][:k]
    samples = []
    for i in idx:
        try:
            txt = getattr(pool[i], "text", "") or getattr(getattr(pool[i], "node", None), "text", "") or str(pool[i])[:800]
        except Exception:
            txt = ""
        samples.append(txt[:500].replace("\n", " ").strip())
    return [s for s in samples if s]

def discover_entity_types(nodes: list, llm, base_dir: str, force: bool = False) -> list[str]:
    """
    Retorna lista de tipos adicionais (0-4). Usa cache em disco; chama LLM só se force ou cache ausente.
    Falha → [] (usa só fixos). Nunca levanta.
    """
    if not force:
        cached = _load_cached(base_dir)
        if cached is not None:
            log.info("[Ontology] Cache hit: %s", cached)
            return cached

    samples = _sample_chunks(nodes)
    if not samples:
        log.info("[Ontology] Sem amostras — usando só tipos fixos")
        _save_cached(base_dir, [])
        return []

    fixed_str = ", ".join(sorted(_FIXED_TYPES))
    sample_str = "\n".join(f"- {s}" for s in samples)
    prompt = _ONTOLOGY_PROMPT.format(fixed=fixed_str, sample=sample_str)

    try:
        resp = llm.complete(prompt)
        text = (resp.text or "").strip()
        # extrai JSON (robusto a cercas markdown)
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("sem JSON")
        data = json.loads(text[start:end + 1])
        raw_types = data.get("entity_types", [])
        cleaned: list[str] = []
        for item in raw_types:
            name = (item.get("name") if isinstance(item, dict) else str(item)).strip()
            # normaliza PascalCase sem acento/espaço
            name = "".join(ch for ch in name if ch.isalnum())
            if not name:
                continue
            name = name[0].upper() + name[1:]
            if name in _FIXED_TYPES or name in cleaned:
                continue
            if 3 <= len(name) <= 20:
                cleaned.append(name)
            if len(cleaned) >= 4:
                break
        log.info("[Ontology] Descobertos: %s", cleaned)
        _save_cached(base_dir, cleaned, raw=data)
        return cleaned
    except Exception as exc:
        log.warning("[Ontology] falha (%s) — usando só fixos", exc)
        _save_cached(base_dir, [])
        return []

def ontology_enabled() -> bool:
    return os.getenv("RAG_ONTOLOGY_DISCOVER", "0").strip().lower() in {"1", "true", "yes", "on"}
