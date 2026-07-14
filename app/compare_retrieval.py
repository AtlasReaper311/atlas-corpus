"""Side-by-side vector-only versus hybrid retrieval on real queries.

Run inside the container so it shares the live Chroma and Ollama:

    docker compose exec corpus python -m app.compare_retrieval
    docker compose exec corpus python -m app.compare_retrieval "zone_id" "522"

Both retrievers run in this one process against the same collection, so
the output is genuine before/after evidence rather than two separate
deploys compared from memory. The default queries lean on exact
identifiers, which is where vector-only retrieval is weakest and the
BM25 half earns its place.
"""

from __future__ import annotations

import sys

import httpx

from app.config import Settings
from app.hybrid import HybridIndex
from app.searcher import connect_collection, hybrid_search, search

DEFAULT_QUERIES = [
    "why do routes use zone_id instead of zone_name",
    "CORPUS_SECRET",
    "worker to worker 522",
    "how do deploys reach Cloudflare",
    "conditional KV write on state change",
]

TOP_N = 3


def _embed(settings: Settings, query: str) -> list[float]:
    """Embed one query synchronously through Ollama's /api/embed."""
    url = f"{settings.ollama_host.rstrip('/')}/api/embed"
    response = httpx.post(
        url,
        json={"model": settings.embed_model, "input": query},
        timeout=60.0,
    )
    response.raise_for_status()
    payload = response.json()
    embeddings = payload.get("embeddings")
    if embeddings:
        return embeddings[0]
    return payload["embedding"]


def _row(rank: int, hit) -> str:
    path = f"{hit.source_repo}/{hit.file_path}".strip("/")
    preview = " ".join(hit.text.split())[:70]
    return f"{rank}. `{path}` ({hit.score:.3f}) {preview}"


def main(argv: list[str]) -> int:
    queries = argv or DEFAULT_QUERIES
    settings = Settings()
    collection = connect_collection(settings)
    index = HybridIndex()
    index.ensure_fresh(collection, None)

    lines: list[str] = ["# retrieval comparison", ""]
    for query in queries:
        embedding = _embed(settings, query)
        vector_hits = search(collection, embedding, TOP_N)
        hybrid_hits = hybrid_search(collection, index, embedding, query, TOP_N)
        lines.append(f"## {query}")
        lines.append("")
        lines.append("| # | vector only | hybrid |")
        lines.append("|---|---|---|")
        for rank in range(TOP_N):
            left = _row(rank + 1, vector_hits[rank]) if rank < len(vector_hits) else ""
            right = _row(rank + 1, hybrid_hits[rank]) if rank < len(hybrid_hits) else ""
            lines.append(f"| {rank + 1} | {left} | {right} |")
        lines.append("")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
