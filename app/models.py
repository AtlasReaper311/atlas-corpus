"""Pydantic models for every request and response shape."""

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """A semantic query against the corpus."""

    query: str = Field(min_length=1, max_length=500)
    top_k: int | None = Field(default=None, ge=1, le=10)


class SearchHit(BaseModel):
    """One retrieved chunk with its provenance."""

    text: str
    score: float
    source_repo: str
    file_path: str
    doc_type: str
    last_updated: str
    chunk_index: int


class SearchResponse(BaseModel):
    """Ranked hits plus timing."""

    query: str
    hits: list[SearchHit]
    took_ms: int


class IndexEntry(BaseModel):
    """One indexed document with its chunk count."""

    source_repo: str
    file_path: str
    doc_type: str
    chunks: int
    last_updated: str


class IndexResponse(BaseModel):
    """Everything currently in the corpus."""

    documents: list[IndexEntry]
    total_documents: int
    total_chunks: int
    last_refresh: str | None


class RefreshResponse(BaseModel):
    """Acknowledgement that a re-ingest was started or is running."""

    status: str
    last_refresh: str | None


class StatsResponse(BaseModel):
    """Aggregate query counts; query text and client identity stay out
    by design (aggregates are publishable, visitor queries are not)."""

    queries_last_hour: int
    queries_today: int
    queries_total: int
    last_query_at: str | None
    generated_at: str


class HealthResponse(BaseModel):
    """Service health plus dependency reachability."""

    ok: bool
    service: str
    version: str
    chroma_ok: bool
    ollama_ok: bool
    documents: int
    chunks: int
    refreshing: bool
