"""ChromaDB connection and semantic search for the corpus."""

import logging
import time

import chromadb
from chromadb.api.models.Collection import Collection

from app.config import Settings
from app.models import SearchHit

logger = logging.getLogger(__name__)

READINESS_ATTEMPTS = 30
READINESS_DELAY_SECONDS = 2.0


def connect_collection(settings: Settings) -> Collection:
    """Connect to Chroma with retries and open the corpus collection.

    Cosine space is set at creation time: with normalised embeddings it
    makes distance interpretable (score = 1 - distance), and it cannot
    be changed after the collection exists.
    """
    last_error: Exception | None = None
    for attempt in range(1, READINESS_ATTEMPTS + 1):
        try:
            client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
            client.heartbeat()
            collection = client.get_or_create_collection(
                name=settings.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                "Chroma ready at %s:%d, collection %s (%d chunks)",
                settings.chroma_host,
                settings.chroma_port,
                settings.collection_name,
                collection.count(),
            )
            return collection
        except Exception as exc:  # noqa: BLE001 - any failure means "not ready"
            last_error = exc
            logger.info(
                "Waiting for Chroma at %s:%d (attempt %d/%d)",
                settings.chroma_host,
                settings.chroma_port,
                attempt,
                READINESS_ATTEMPTS,
            )
            time.sleep(READINESS_DELAY_SECONDS)
    raise RuntimeError(f"Chroma unreachable: {last_error}")


def search(collection: Collection, embedding: list[float], k: int) -> list[SearchHit]:
    """Top-k chunks for a query embedding, best first."""
    total = collection.count()
    if total == 0:
        return []
    result = collection.query(
        query_embeddings=[embedding],
        n_results=min(k, total),
        include=["documents", "metadatas", "distances"],
    )
    hits: list[SearchHit] = []
    for document, meta, distance in zip(
        result["documents"][0], result["metadatas"][0], result["distances"][0]
    ):
        hits.append(
            SearchHit(
                text=document,
                score=round(1.0 - float(distance), 4),
                source_repo=str(meta.get("source_repo", "")),
                file_path=str(meta.get("file_path", "")),
                doc_type=str(meta.get("doc_type", "")),
                last_updated=str(meta.get("last_updated", "")),
                chunk_index=int(meta.get("chunk_index", 0)),
            )
        )
    return hits
