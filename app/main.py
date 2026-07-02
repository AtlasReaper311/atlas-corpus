"""FastAPI service: the queryable knowledge layer over Atlas Systems.

Surface split by trust level. GET/POST /search is public because browsers
call it from the site widget, so it carries the protections the edge
would normally provide: per-IP rate limiting, query length caps, and a
CORS allowlist. POST /refresh mutates state and is gated by
CORPUS_SECRET, fail-closed at startup exactly like the rag stack's
ATLAS_SECRET. GET /index and GET /health are read-only and public.

Ingest runs in the background: at startup, on demand via /refresh, and
optionally on a timer. A lock makes refreshes single-flight; a second
trigger while one runs is acknowledged, not queued, because ingest is
idempotent and the next push will refresh again anyway.
"""

import asyncio
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.config import SERVICE_NAME, SERVICE_VERSION, Settings, get_settings
from app.embedder import embed_batch, embed_query
from app.ingester import run_ingest
from app.models import (
    HealthResponse,
    IndexEntry,
    IndexResponse,
    RefreshResponse,
    SearchRequest,
    SearchResponse,
)
from app.searcher import connect_collection, search

logger = logging.getLogger(__name__)

READINESS_ATTEMPTS = 30
READINESS_DELAY_SECONDS = 2.0


async def _wait_for_ollama(client: httpx.AsyncClient, settings: Settings) -> None:
    """Block until Ollama answers /api/tags, or raise after the budget."""
    for attempt in range(1, READINESS_ATTEMPTS + 1):
        try:
            response = await client.get(
                f"{settings.ollama_host}/api/tags",
                timeout=settings.health_timeout_seconds,
            )
            response.raise_for_status()
            logger.info("Ollama reachable at %s", settings.ollama_host)
            return
        except Exception:  # noqa: BLE001
            logger.info(
                "Waiting for Ollama at %s (attempt %d/%d)",
                settings.ollama_host,
                attempt,
                READINESS_ATTEMPTS,
            )
            await asyncio.sleep(READINESS_DELAY_SECONDS)
    raise RuntimeError(f"Ollama unreachable at {settings.ollama_host}")


# --------------------------------------------------------------------- #
# Refresh orchestration                                                   #
# --------------------------------------------------------------------- #


async def _refresh(app: FastAPI, reason: str) -> None:
    """One single-flight ingest pass; concurrent triggers are dropped."""
    if app.state.refresh_lock.locked():
        logger.info("refresh (%s) skipped: one is already running", reason)
        return
    async with app.state.refresh_lock:
        logger.info("refresh started (%s)", reason)
        try:
            stats = await run_ingest(
                app.state.client, app.state.settings, app.state.collection, embed_batch
            )
            app.state.index = stats.pop("index")
            app.state.last_refresh = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            app.state.last_stats = dict(stats)
        except Exception:  # noqa: BLE001 - a failed refresh keeps the old corpus
            logger.exception("refresh (%s) failed; previous corpus stays live", reason)


async def _periodic_refresh(app: FastAPI) -> None:
    """Optional timer-driven refresh; the push trigger is the primary path."""
    interval = app.state.settings.refresh_interval_seconds
    while True:
        try:
            await asyncio.sleep(interval)
            await _refresh(app, reason="interval")
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
            logger.exception("periodic refresh pass failed; continuing")


# --------------------------------------------------------------------- #
# App wiring                                                              #
# --------------------------------------------------------------------- #


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start order: settings (fail-closed secret), Ollama, Chroma, ingest."""
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if not settings.corpus_secret:
        # Tunnel-exposed service, mutating endpoint: refuse to start open.
        raise RuntimeError(
            "CORPUS_SECRET is not set. Generate one with "
            "python -c \"import secrets; print(secrets.token_urlsafe(48))\" "
            "and set it in .env; docker-compose.yml enforces the same."
        )
    app.state.settings = settings
    app.state.client = httpx.AsyncClient()
    await _wait_for_ollama(app.state.client, settings)
    app.state.collection = connect_collection(settings)
    app.state.index = {}
    app.state.last_refresh = None
    app.state.last_stats = {}
    app.state.refresh_lock = asyncio.Lock()
    app.state.rate_buckets = defaultdict(deque)

    startup_ingest = asyncio.create_task(_refresh(app, reason="startup"))
    periodic_task = None
    if settings.refresh_interval_seconds > 0:
        periodic_task = asyncio.create_task(_periodic_refresh(app))
    logger.info("%s %s ready", SERVICE_NAME, SERVICE_VERSION)
    yield
    startup_ingest.cancel()
    with suppress(asyncio.CancelledError):
        await startup_ingest
    if periodic_task:
        periodic_task.cancel()
        with suppress(asyncio.CancelledError):
            await periodic_task
    await app.state.client.aclose()


app = FastAPI(title=SERVICE_NAME, version=SERVICE_VERSION, lifespan=lifespan)

_settings_for_cors = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in _settings_for_cors.allowed_origins.split(",")
        if origin.strip()
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["content-type", "x-corpus-secret"],
    max_age=86400,
)


def _client_ip(request: Request) -> str:
    """The caller's IP: Cloudflare's header through the tunnel, else socket."""
    return request.headers.get("cf-connecting-ip") or (
        request.client.host if request.client else "unknown"
    )


def _rate_limit(app: FastAPI, ip: str) -> None:
    """Sliding one-hour window per IP; over the cap answers 429."""
    limit = app.state.settings.rate_limit_per_hour
    bucket = app.state.rate_buckets[ip]
    now = time.time()
    while bucket and now - bucket[0] > 3600:
        bucket.popleft()
    if len(bucket) >= limit:
        raise HTTPException(status_code=429, detail="rate limit: try again later")
    bucket.append(now)


def _require_secret(request: Request) -> None:
    """Gate for mutating endpoints; compared against the fail-closed secret."""
    provided = request.headers.get("x-corpus-secret", "")
    if provided != app.state.settings.corpus_secret:
        raise HTTPException(status_code=401, detail="unauthorised")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Convenience redirect to the interactive docs."""
    return RedirectResponse(url="/docs")


async def _run_search(payload: SearchRequest, request: Request) -> SearchResponse:
    """Shared search path for browser POSTs and URL/query-string GETs."""
    _rate_limit(app, _client_ip(request))
    settings: Settings = app.state.settings
    started = time.time()
    embedding = await embed_query(app.state.client, settings, payload.query)
    k = min(payload.top_k or settings.top_k_default, settings.top_k_max)
    hits = search(app.state.collection, embedding, k)
    return SearchResponse(
        query=payload.query,
        hits=hits,
        took_ms=int((time.time() - started) * 1000),
    )


@app.post("/search", response_model=SearchResponse)
async def search_corpus(payload: SearchRequest, request: Request) -> SearchResponse:
    """Public semantic search with per-IP rate limiting."""
    return await _run_search(payload, request)


@app.get("/search", response_model=SearchResponse)
async def search_corpus_get(
    request: Request,
    q: str | None = Query(default=None, min_length=1, max_length=500),
    query: str | None = Query(default=None, min_length=1, max_length=500),
    top_k: int | None = Query(default=None, ge=1, le=10),
) -> SearchResponse:
    """GET-compatible search for direct browser URLs and no-preflight clients."""
    text = q or query
    if not text:
        raise HTTPException(status_code=400, detail="query is required")
    return await _run_search(SearchRequest(query=text, top_k=top_k), request)


@app.get("/index", response_model=IndexResponse)
def index_listing() -> IndexResponse:
    """Everything indexed, from the last completed ingest pass."""
    entries = [IndexEntry(**entry) for entry in app.state.index.values()]
    entries.sort(key=lambda e: (e.source_repo, e.file_path))
    return IndexResponse(
        documents=entries,
        total_documents=len(entries),
        total_chunks=sum(entry.chunks for entry in entries),
        last_refresh=app.state.last_refresh,
    )


@app.post("/refresh", response_model=RefreshResponse, status_code=202)
async def refresh(request: Request) -> RefreshResponse:
    """Secret-gated re-ingest; returns immediately, work runs behind."""
    _require_secret(request)
    if app.state.refresh_lock.locked():
        return RefreshResponse(status="already_running", last_refresh=app.state.last_refresh)
    asyncio.create_task(_refresh(app, reason="webhook"))
    return RefreshResponse(status="started", last_refresh=app.state.last_refresh)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Service health plus dependency reachability and corpus size."""
    settings: Settings = app.state.settings
    try:
        chunks = app.state.collection.count()
        chroma_ok = True
    except Exception:  # noqa: BLE001
        chunks = 0
        chroma_ok = False
    try:
        response = await app.state.client.get(
            f"{settings.ollama_host}/api/tags", timeout=settings.health_timeout_seconds
        )
        ollama_ok = response.status_code == 200
    except Exception:  # noqa: BLE001
        ollama_ok = False
    return HealthResponse(
        ok=chroma_ok and ollama_ok,
        service=SERVICE_NAME,
        version=SERVICE_VERSION,
        chroma_ok=chroma_ok,
        ollama_ok=ollama_ok,
        documents=len(app.state.index),
        chunks=chunks,
        refreshing=app.state.refresh_lock.locked(),
    )
