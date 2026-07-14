"""ChromaDB connection and semantic search for the corpus.

The vector-only primitives connect_collection and search are unchanged
from before hybrid retrieval landed; hybrid_search is added alongside
them and fuses vector ranking with the BM25 ranking from app.hybrid.
The vector path stays intact so the comparison script can run both in
one process and show the difference on real queries.
"""

import logging
import time

import chromadb
from chromadb.api.models.Collection import Collection

from app.config import Settings
from app.hybrid import HybridIndex, cosine_similarity, rrf_fuse
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


def _hit_from(document: str, meta: dict, score: float) -> SearchHit:
    return SearchHit(
        text=document,
        score=round(float(score), 4),
        source_repo=str(meta.get("source_repo", "")),
        file_path=str(meta.get("file_path", "")),
        doc_type=str(meta.get("doc_type", "")),
        last_updated=str(meta.get("last_updated", "")),
        chunk_index=int(meta.get("chunk_index", 0)),
    )


def hybrid_search(
    collection: Collection,
    index: HybridIndex,
    embedding: list[float],
    query_text: str,
    k: int,
    freshness_marker=None,
) -> list[SearchHit]:
    """Top-k chunks by RRF over vector and BM25 rankings.

    Both retrievers pull a pool wider than k, RRF fuses their rankings,
    and the top k ids are returned. The reported score stays true
    cosine similarity, not the fusion score: cosine is what the widget
    and callers already read as match quality, and RRF scores are tiny
    and scale-free. A consequence is that scores may not decrease
    monotonically down the list, because a chunk BM25 lifted into the
    top k can carry a lower cosine than one below it; the ordering is
    the fusion's, the number is the honest similarity.
    """
    total = collection.count()
    if total == 0:
        return []
    index.ensure_fresh(collection, freshness_marker)
    pool = min(max(k * 4, 20), total)

    vector = collection.query(
        query_embeddings=[embedding],
        n_results=pool,
        include=["documents", "metadatas", "distances"],
    )
    cached: dict[str, tuple[str, dict, float]] = {}
    vector_ranking: list[str] = []
    for cid, document, meta, distance in zip(
        vector["ids"][0],
        vector["documents"][0],
        vector["metadatas"][0],
        vector["distances"][0],
    ):
        cached[cid] = (document, meta, 1.0 - float(distance))
        vector_ranking.append(cid)

    bm25_ranking = index.ranked_ids(query_text, pool)

    fused = rrf_fuse([vector_ranking, bm25_ranking])
    top_ids = [cid for cid, _ in fused[:k]]

    # BM25-only ids never went through the vector query, so their true
    # cosine is not known yet; fetch their stored embeddings and compute
    # it, so every returned score is a real similarity to this query.
    missing = [cid for cid in top_ids if cid not in cached]
    if missing:
        fetched = collection.get(
            ids=missing,
            include=["documents", "metadatas", "embeddings"],
        )
        fetched_embeddings = fetched.get("embeddings")
        if fetched_embeddings is None:
            fetched_embeddings = []
        for position, cid in enumerate(fetched.get("ids", [])):
            document = fetched["documents"][position]
            meta = fetched["metadatas"][position]
            stored = fetched_embeddings[position] if position < len(fetched_embeddings) else None
            # Chroma returns embeddings as numpy arrays; "is not None"
            # and len() avoid the truthiness ambiguity of an array.
            if stored is not None and len(stored):
                similarity = cosine_similarity(embedding, list(stored))
            else:
                similarity = 0.0
            cached[cid] = (document, meta, similarity)

    hits: list[SearchHit] = []
    for cid in top_ids:
        entry = cached.get(cid)
        if entry is None:
            continue
        document, meta, similarity = entry
        hits.append(_hit_from(document, meta, similarity))
    return hits
