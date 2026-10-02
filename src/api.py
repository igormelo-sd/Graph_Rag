"""
API — FastAPI app do RAG Estatístico SP (RAG Principal).

Endpoints:
    POST /query   — recebe pergunta, retorna resposta + fontes + validação numérica
    GET  /health  — verifica se o sistema está pronto
    GET  /metrics — métricas Prometheus
"""
import os
import sys
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from api_security import (
    SecurityHeadersMiddleware,
    cors_origins,
    enforce_rate_limit,
    require_api_key,
)
from logger import get_logger, setup_logging
from api_models import QueryRequest, QueryResponse
from query_service import execute_engine_query
from metrics import MetricsMiddleware, render_prometheus
from query_interpreter import interpret_query
from startup import initialize
from load_control import CapacityExceeded

RAG_TYPE = "principal"
RAG_LABEL = "RAG Principal"

log = get_logger(__name__)

# ── Estado global da aplicação ────────────────────────────────────────────────

_engine = None
_interp_llm = None


def _frontend_dir() -> str:
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
    )


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine, _interp_llm

    setup_logging()

    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _engine, _interp_llm = initialize(base_dir)
    log.info("API pronta para receber requisicoes")

    yield  # API ativa

    _engine = None
    _interp_llm = None
    log.info("API encerrada")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="RAG Estatístico SP - RAG Principal",
    description="Sistema de perguntas e respostas sobre dados econômicos do Estado de São Paulo.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(MetricsMiddleware, service_name=RAG_TYPE)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root():
    if os.path.isdir(_frontend_dir()):
        return RedirectResponse(url="/app/")
    return RedirectResponse(url="/docs")


@app.get("/health")
async def health():
    # Health profundo: checa engine + Chroma + BM25 + embedding (sem chamar LLM)
    details: dict = {
        "engine_ready": _engine is not None,
        "interp_ready": _interp_llm is not None,
        "rag_type": RAG_TYPE,
        "rag_label": RAG_LABEL,
    }
    try:
        from indexing import load_nodes_cache
        from index_manifest import resolve_db_dir

        try:
            db_path = resolve_db_dir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        except Exception:
            db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chroma_db")
        bm25_nodes = load_nodes_cache(db_path)
        details["bm25_nodes"] = len(bm25_nodes)
        try:
            import chromadb

            db = chromadb.PersistentClient(path=db_path)
            col = db.get_or_create_collection("estatisticas")
            details["chroma_count"] = col.count()
        except Exception as e:
            details["chroma_error"] = str(e)[:200]
    except Exception as e:
        details["health_error"] = str(e)[:200]
    try:
        from llama_index.core import Settings

        details["embed_model_ready"] = Settings.embed_model is not None
    except Exception:
        details["embed_model_ready"] = False
    # status agregado
    ok = bool(details.get("engine_ready") and details.get("chroma_count", 0) > 0 and details.get("bm25_nodes", 0) > 0)
    details["status"] = "ok" if ok else ("degraded" if details.get("engine_ready") else "starting")
    return details


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return render_prometheus()


@app.post("/query", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    _rl: None = Depends(enforce_rate_limit),
    _auth: None = Depends(require_api_key),
):
    if _engine is None or _interp_llm is None:
        raise HTTPException(status_code=503, detail="Sistema ainda não inicializado.")

    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="A pergunta não pode ser vazia.")

    t0 = time.monotonic()
    log.info(
        "Requisicao recebida",
        extra={"question": question[:120]},
    )

    try:
        response, diagnostics = await execute_engine_query(
            question=question,
            engine=_engine,
            interp_llm=_interp_llm,
            interpreter=interpret_query,
            rag_type=RAG_TYPE,
            rag_label=RAG_LABEL,
        )
        latency_ms = round((time.monotonic() - t0) * 1000)
        log.info(
            "Requisicao concluida",
            extra={
                "question": question[:120],
                "sources": diagnostics.sources,
                "chunks": diagnostics.chunks,
                "latency_ms": latency_ms,
                "verified": f"{diagnostics.verified}/{diagnostics.total}",
                "estimated_input_tokens": diagnostics.estimated_input_tokens,
                "estimated_output_tokens": diagnostics.estimated_output_tokens,
                "estimated_cost_usd": diagnostics.estimated_cost_usd,
            },
        )
        if diagnostics.unverified:
            log.warning(
                "Numeros nao verificados na resposta",
                extra={"question": question[:120], "unverified": diagnostics.unverified},
            )

    except CapacityExceeded as exc:
        raise HTTPException(status_code=503, detail="Sistema ocupado. Tente novamente em instantes.", headers={"Retry-After": "5"}) from exc
    except TimeoutError as exc:
        log.warning("Timeout global ao processar requisicao", extra={"question": question[:120]})
        raise HTTPException(status_code=504, detail="Tempo limite da requisição excedido.") from exc
    except Exception as exc:
        latency_ms = round((time.monotonic() - t0) * 1000)
        log.error(
            "Erro ao processar requisicao",
            extra={"question": question[:120], "latency_ms": latency_ms},
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Falha interna ao processar a consulta."
        ) from exc

    return response


_frontend_path = _frontend_dir()
if os.path.isdir(_frontend_path):
    app.mount(
        "/app",
        StaticFiles(directory=_frontend_path, html=True),
        name="frontend",
    )
