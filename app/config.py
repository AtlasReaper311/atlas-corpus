"""Typed configuration for the corpus service.

Every tunable lives here and is overridable from the environment.
Defaults are duplicated as ${VAR:-default} in docker-compose.yml so
the stack boots with no .env at all, except CORPUS_SECRET, which is
deliberately fail-closed: a tunnel-exposed service with an unset
secret must refuse to start, not start open.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_NAME = "atlas-corpus"
SERVICE_VERSION = "1.1.0"


class Settings(BaseSettings):
    """All runtime configuration, sourced from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Ollama runs outside compose on the host, so the default targets
    # the host gateway; extra_hosts maps it on native Linux too.
    ollama_host: str = "http://host.docker.internal:11434"
    embed_model: str = "nomic-embed-text"
    answer_model: str = "mistral:7b"
    embed_batch_size: int = 16
    embed_timeout_seconds: float = 120.0
    answer_timeout_seconds: float = 180.0
    health_timeout_seconds: float = 5.0

    chroma_host: str = "chromadb"
    chroma_port: int = 8000
    collection_name: str = "atlas_corpus"

    # GitHub ingestion. The token is optional for public repos but
    # strongly recommended: unauthenticated GitHub API allows 60
    # requests/hour, a full ingest uses more.
    github_owner: str = "AtlasReaper311"
    github_token: str = ""
    # Repos never worth indexing: forks of other people's work, the
    # profile repo, anything archived is skipped automatically.
    exclude_repos: str = "AtlasReaper311"
    # HTML sources inside the site repo, prefix → doc_type.
    site_repo: str = "atlas-systems"
    case_study_prefix: str = "work/"
    article_prefix: str = "writing/"
    # Pinned extra files, "repo:path:doc_type" comma-separated.
    extra_files: str = "atlas-infra:docs/decisions.md:decision"
    # Local documents (the brand doc, the context doc) mounted read-only.
    docs_dir: str = "/srv/docs"

    # Chunking: word-based, sized to approximate the specced 512 tokens
    # with 64 of overlap. nomic-embed-text's window (8192) dwarfs it.
    chunk_words: int = 512
    chunk_overlap_words: int = 64

    # Search protections: the endpoint is public (the site widget calls
    # it from browsers), so ramone-edge's protections move down a layer.
    top_k_default: int = 5
    top_k_max: int = 10
    query_max_chars: int = 500
    rate_limit_per_hour: int = 60
    allowed_origins: str = (
        "https://atlas-systems.uk,https://www.atlas-systems.uk,http://localhost:8788"
    )

    # Mutation gate: required, no default (fail-closed at startup).
    corpus_secret: str = ""

    # Periodic re-ingest in seconds; 0 disables it because the push
    # trigger (github-trigger/) is the primary freshness mechanism.
    refresh_interval_seconds: int = 0
    # Startup re-ingest is disabled by default. The persisted Chroma
    # collection is restored immediately at boot, and push/manual
    # refreshes own freshness. Set to 0 for immediate startup refresh,
    # or a positive delay in seconds if a host needs warm-up time.
    startup_refresh_delay_seconds: int = -1

    # Query logging and the hourly stats summary. SQLite on the data
    # volume, not KV at the edge: logging stays inside the hot path's
    # own failure domain and never costs a network write per query.
    # An empty report key disables the summariser; logging itself is
    # always on, being local and free.
    query_log_path: str = "/srv/data/queries.db"
    rag_report_url: str = "https://api.atlas-systems.uk/v1/rag/report"
    rag_report_key: str = ""
    rag_summary_interval_seconds: int = 3600

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance (lazy singleton)."""
    return Settings()
