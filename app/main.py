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

Every real /search is logged to SQLite on the data volume (query text,
result count, latency; never IPs), GET /stats serves the aggregates,
and an hourly task posts a summary to atlas-api-public, which relays
active hours to #rag-queries. Sentinel canaries (internal header from a
loopback or private address) are exempt from logging and rate limiting,
so monitoring never pollutes the stats it sits beside.
"""

import asyncio
import html
import ipaddress
import logging
import re
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app import querylog
from app.config import SERVICE_NAME, SERVICE_VERSION, Settings, get_settings
from app.embedder import embed_batch, embed_query
from app.index_state import restore_index_from_collection as _restore_index_from_collection
from app.ingester import run_ingest
from app.models import (
    AskResponse,
    AskSource,
    HealthResponse,
    IndexEntry,
    IndexResponse,
    RefreshResponse,
    SearchRequest,
    SearchResponse,
    StatsResponse,
)
from app.searcher import connect_collection, search

logger = logging.getLogger(__name__)

READINESS_ATTEMPTS = 30
READINESS_DELAY_SECONDS = 2.0

PRIVATE_BOUNDARY_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\b(cv|curriculum vitae|resume|cover letter|salary|interview|job application|application material)\b",
            re.IGNORECASE,
        ),
        "That is private application material. I can answer from the public Atlas Systems estate instead.",
    ),
    (
        re.compile(
            r"\b(university notes?|lecture notes?|study notes?|coursework|grades?|marks?|academic drafts?|honours drafts?|abertay)\b",
            re.IGNORECASE,
        ),
        "That is private academic material. I can answer from the public Atlas Systems estate instead.",
    ),
    (
        re.compile(
            r"\b(books?|reading notes?|reference library|private library|licensed third-party text)\b",
            re.IGNORECASE,
        ),
        "That is private reference material. I can answer from the public Atlas Systems estate instead.",
    ),
    (
        re.compile(
            r"\b(soh|employer material|employer code|employer meetings?|employer architecture|work macbook|colleagues?|slack|tickets?)\b",
            re.IGNORECASE,
        ),
        "That is employer material. I can answer from the public Atlas Systems estate instead.",
    ),
    (
        re.compile(
            r"\b(secret|token|api key|password|credential|\.env|webhook value|trigger_secret|corpus_secret|github_token)\b",
            re.IGNORECASE,
        ),
        "That is secret or credential material. I can answer from the public Atlas Systems estate instead.",
    ),
    (
        re.compile(
            r"\b(what did atlas ask you to remember|what did atlas tell you to remember|remember to help|remember this today|private memory|ramone_memory)\b",
            re.IGNORECASE,
        ),
        "That is private memory. I can answer from the public Atlas Systems estate instead.",
    ),
)


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


async def _delayed_startup_refresh(app: FastAPI) -> None:
    """Optional startup refresh after the service is already live."""
    delay = app.state.settings.startup_refresh_delay_seconds
    if delay > 0:
        await asyncio.sleep(delay)
    await _refresh(app, reason="startup")


def _iso(ts: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


async def _post_summary(app: FastAPI, window_seconds: int) -> None:
    """Compute one window's summary from SQLite and POST it to the edge.

    Count 0 still posts: the edge refreshes the card's last-known-good
    and skips Discord, so quiet hours stay quiet without going stale.
    """
    settings: Settings = app.state.settings
    until = int(time.time())
    since = until - window_seconds
    summary = await asyncio.to_thread(
        querylog.window_summary, settings.query_log_path, since, until
    )
    totals = await asyncio.to_thread(querylog.stats, settings.query_log_path)
    payload = {
        "source": SERVICE_NAME,
        "window_start": _iso(since),
        "window_end": _iso(until),
        "count": summary["count"],
        "top_terms": summary["top_terms"],
        "queries_today": totals["queries_today"],
        "queries_total": totals["queries_total"],
        "last_query_at": totals["last_query_at"],
    }
    response = await app.state.client.post(
        settings.rag_report_url,
        json=payload,
        headers={"authorization": f"Bearer {settings.rag_report_key}"},
        timeout=10.0,
    )
    logger.info(
        "query summary posted: %d queries, edge answered %d",
        summary["count"],
        response.status_code,
    )


async def _periodic_query_summary(app: FastAPI) -> None:
    """Hourly query summary loop; the window rides in the payload, so a
    drifting start time can never corrupt the numbers. Every failure
    logs and continues, because stats must never take down search."""
    interval = app.state.settings.rag_summary_interval_seconds
    while True:
        try:
            await asyncio.sleep(interval)
            await _post_summary(app, interval)
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
            logger.exception("query summary pass failed; continuing")


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
    app.state.index = _restore_index_from_collection(app.state.collection)
    app.state.last_refresh = None
    app.state.last_stats = {
        "documents": len(app.state.index),
        "chunks": app.state.collection.count(),
        "deleted": 0,
        "skipped": 0,
    }
    app.state.refresh_lock = asyncio.Lock()
    app.state.rate_buckets = defaultdict(deque)

    startup_ingest = None
    if settings.startup_refresh_delay_seconds >= 0:
        startup_ingest = asyncio.create_task(_delayed_startup_refresh(app))
    else:
        logger.info(
            "startup refresh disabled; restored %d docs from persisted corpus",
            len(app.state.index),
        )
    periodic_task = None
    if settings.refresh_interval_seconds > 0:
        periodic_task = asyncio.create_task(_periodic_refresh(app))
    summary_task = None
    if (
        settings.rag_report_key
        and settings.rag_report_url
        and settings.rag_summary_interval_seconds > 0
    ):
        summary_task = asyncio.create_task(_periodic_query_summary(app))
    logger.info("%s %s ready", SERVICE_NAME, SERVICE_VERSION)
    yield
    if startup_ingest:
        startup_ingest.cancel()
        with suppress(asyncio.CancelledError):
            await startup_ingest
    if periodic_task:
        periodic_task.cancel()
        with suppress(asyncio.CancelledError):
            await periodic_task
    if summary_task:
        summary_task.cancel()
        with suppress(asyncio.CancelledError):
            await summary_task
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


def _is_internal(request: Request) -> bool:
    """True only for loopback or private callers carrying the internal
    header. specular-sentinel's search canary must not pollute the query
    log or spend the public rate budget; the header alone is spoofable
    from the internet, the source address alone would exempt every LAN
    client, so exemption requires both."""
    if "x-atlas-internal" not in request.headers:
        return False
    ip = _client_ip(request)
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.is_loopback or addr.is_private


def _log_query_fire_and_forget(query: str, result_count: int, took_ms: int) -> None:
    """Schedule the SQLite insert off the event loop and move on; the
    logger swallows its own failures, the callback just retrieves any
    exception so asyncio never warns about an unconsumed one."""
    path = app.state.settings.query_log_path
    task = asyncio.create_task(
        asyncio.to_thread(querylog.log_query, path, query, result_count, took_ms)
    )
    task.add_done_callback(lambda t: t.exception())


def _private_boundary_refusal(query: str) -> str | None:
    """Public corpus guard for obvious private-material requests.

    This does not replace retrieval boundaries; it stops short sensitive
    queries from depending on vector ranking to find the refusal document.
    """
    for pattern, answer in PRIVATE_BOUNDARY_RULES:
        if pattern.search(query):
            return answer
    return None


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


def _display_excerpt(text: str, limit: int = 260) -> str:
    """Compact retrieved text for source tags without changing retrieval."""
    cleaned = html.unescape(re.sub(r"<[^>]+>", " ", text))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "..."


def _source_from_hit(
    hit,
    limit: int = 260,
    question: str | None = None,
) -> AskSource:
    return AskSource(
        repo=hit.source_repo,
        file=hit.file_path,
        excerpt=(
            _prompt_excerpt(hit.text, question, limit=limit)
            if question
            else _display_excerpt(hit.text, limit=limit)
        ),
    )


def _prompt_excerpt(text: str, question: str | None = None, limit: int = 900) -> str:
    """Keep /ask compact while showing the part most likely to answer."""
    cleaned = html.unescape(re.sub(r"<[^>]+>", " ", text))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= limit:
        return cleaned

    focus = 0
    if question:
        stopwords = {
            "about",
            "does",
            "from",
            "have",
            "what",
            "when",
            "where",
            "which",
            "with",
            "would",
        }
        raw_terms = [
            term.lower()
            for term in re.findall(r"[A-Za-z0-9_-]{4,}", question)
            if term.lower() not in stopwords
        ]
        domain_terms = {"atlas", "public", "ramone", "systems"}
        specific_terms = [term for term in raw_terms if term not in domain_terms]
        terms = specific_terms or raw_terms
        lower = cleaned.lower()
        positions = [(lower.find(term), term) for term in terms]
        matches = [(pos, term) for pos, term in positions if pos >= 0]
        if matches:
            # Prefer the most specific matching term, then center around it.
            pos, term = max(matches, key=lambda item: (len(item[1]), -item[0]))
            focus = max(0, pos - max(80, limit // 4))

    snippet = cleaned[focus : focus + limit].strip()
    prefix = "..." if focus else ""
    suffix = "..." if focus + limit < len(cleaned) else ""
    return f"{prefix}{snippet}{suffix}"


def _answer_declines(answer: str) -> bool:
    lowered = answer.lower()
    return any(
        phrase in lowered
        for phrase in (
            "do not contain",
            "does not contain",
            "don't contain",
            "do not answer",
            "does not answer",
            "cannot answer",
            "can't answer",
            "could not find",
            "not enough information",
            "without guessing",
        )
    )


def _fallback_answer_from_hits(hits) -> AskResponse:
    if not hits:
        return AskResponse(
            answer="I could not find anything in the corpus excerpts that answers that question.",
            sources=[],
        )
    best_score = max(float(hit.score) for hit in hits)
    if best_score < 0.5:
        return AskResponse(
            answer="The retrieved corpus excerpts do not answer that question clearly enough for me to answer without guessing.",
            sources=[],
        )
    sources = [_source_from_hit(hit) for hit in hits[:2]]
    facts = " ".join(source.excerpt for source in sources)
    if len(facts) > 420:
        facts = facts[:419].rstrip() + "..."
    return AskResponse(
        answer=(
            "Answer synthesis did not finish before the public request timeout, "
            f"but the closest corpus excerpts say: {facts}"
        ),
        sources=sources,
    )


async def _answer_from_hits(
    client: httpx.AsyncClient,
    settings: Settings,
    question: str,
    hits,
) -> AskResponse:
    """Ask Ollama for a grounded answer over already-retrieved chunks."""
    if not hits:
        return AskResponse(
            answer="I could not find anything in the corpus excerpts that answers that question.",
            sources=[],
        )

    source_lines = []
    sources_by_id = {}
    for index, hit in enumerate(hits, start=1):
        source = _source_from_hit(hit)
        sources_by_id[index] = source
        source_lines.append(
            f"[{index}] repo: {source.repo}\n"
            f"file: {source.file}\n"
            f"excerpt: {_prompt_excerpt(hit.text, question)}"
        )

    prompt = (
        "Answer using only these excerpts. If they do not answer the question, "
        "say that plainly. Return at most two complete sentences. "
        "Cite facts with [1], [2], etc.\n\n"
        f"Question: {question}\n\nExcerpts:\n\n"
        + "\n\n".join(source_lines)
    )
    try:
        response = await client.post(
            f"{settings.ollama_host}/api/generate",
            json={
                "model": settings.answer_model,
                "prompt": prompt,
                "stream": False,
                "keep_alive": "30m",
                "options": {"temperature": 0.0, "num_ctx": 2048, "num_predict": 140},
            },
            timeout=min(settings.answer_timeout_seconds, 55.0),
        )
    except httpx.TimeoutException:
        return _fallback_answer_from_hits(hits)
    response.raise_for_status()
    answer = str(response.json().get("response") or "").strip()
    if not answer:
        answer = (
            "The retrieved corpus excerpts do not answer that question clearly enough for me to answer without guessing."
        )
    selected_sources: list[AskSource] = []
    declined = _answer_declines(answer)
    if not selected_sources and not declined:
        selected_sources = [_source_from_hit(hit, question=question) for hit in hits[:3]]
    return AskResponse(answer=answer, sources=selected_sources)


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
    internal = _is_internal(request)
    if not internal:
        _rate_limit(app, _client_ip(request))
    settings: Settings = app.state.settings
    started = time.time()
    if not internal and _private_boundary_refusal(payload.query):
        took_ms = int((time.time() - started) * 1000)
        _log_query_fire_and_forget(payload.query, 0, took_ms)
        return SearchResponse(query=payload.query, hits=[], took_ms=took_ms)
    embedding = await embed_query(app.state.client, settings, payload.query)
    k = min(payload.top_k or settings.top_k_default, settings.top_k_max)
    hits = search(app.state.collection, embedding, k)
    took_ms = int((time.time() - started) * 1000)
    if not internal:
        _log_query_fire_and_forget(payload.query, len(hits), took_ms)
    return SearchResponse(query=payload.query, hits=hits, took_ms=took_ms)


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


@app.post("/ask", response_model=AskResponse)
async def ask_corpus(payload: SearchRequest, request: Request) -> AskResponse:
    """Public corpus Q&A: retrieve with /search, then synthesize with Ollama."""
    if not _is_internal(request):
        refusal = _private_boundary_refusal(payload.query)
        if refusal:
            _log_query_fire_and_forget(payload.query, 0, 0)
            return AskResponse(answer=refusal, sources=[])
    search_response = await _run_search(payload, request)
    return await _answer_from_hits(
        app.state.client,
        app.state.settings,
        search_response.query,
        search_response.hits,
    )


@app.get("/ask", response_model=AskResponse)
async def ask_corpus_get(
    request: Request,
    q: str | None = Query(default=None, min_length=1, max_length=500),
    query: str | None = Query(default=None, min_length=1, max_length=500),
    top_k: int | None = Query(default=None, ge=1, le=10),
) -> AskResponse:
    """GET-compatible Q&A for the browser widget and no-preflight clients."""
    text = q or query
    if not text:
        raise HTTPException(status_code=400, detail="query is required")
    return await ask_corpus(SearchRequest(query=text, top_k=top_k), request)


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


@app.get("/stats", response_model=StatsResponse)
async def query_stats() -> StatsResponse:
    """Aggregate query counts; public because it exposes numbers only.

    Top terms deliberately stay out of this response: they surface in
    the private hourly Discord summary and nowhere else."""
    totals = await asyncio.to_thread(
        querylog.stats, app.state.settings.query_log_path
    )
    return StatsResponse(**totals, generated_at=_iso(int(time.time())))


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
        documents=len(app.state.index) or int(app.state.last_stats.get("documents", 0)),
        chunks=chunks,
        refreshing=app.state.refresh_lock.locked(),
    )
