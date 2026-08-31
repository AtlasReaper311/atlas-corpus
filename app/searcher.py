"""ChromaDB connection and semantic search for the corpus.

The vector-only primitives connect_collection and search are unchanged
from before hybrid retrieval landed; hybrid_search is added alongside
them and fuses vector ranking with the BM25 ranking from app.hybrid.
The vector path stays intact so the comparison script can run both in
one process and show the difference on real queries.
"""

import logging
import time
from datetime import datetime, timezone

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
            _hit_from(document, meta, 1.0 - float(distance))
        )
    return hits


def _hit_from(document: str, meta: dict, score: float) -> SearchHit:
    chunk_index = int(meta.get("chunk_index", 0))
    source_repo = str(meta.get("source_repo", ""))
    file_path = str(meta.get("file_path", ""))
    return SearchHit(
        id=str(meta.get("source_id") or f"{source_repo}/{file_path}#{chunk_index}"),
        text=document,
        score=round(float(score), 4),
        source_repo=source_repo,
        file_path=file_path,
        doc_type=str(meta.get("doc_type", "")),
        last_updated=str(meta.get("last_updated", "")),
        chunk_index=chunk_index,
        source_title=str(meta.get("source_title", "")),
        source_url=str(meta.get("source_url", "")),
        public_url=str(meta.get("public_url", "")),
        heading=str(meta.get("heading", "")),
        heading_path=str(meta.get("heading_path", "")),
        source_class=str(meta.get("source_class", "")),
        source_scope=str(meta.get("source_scope", "")),
        source_lifecycle=str(meta.get("source_lifecycle", "")),
        runtime_service=bool(meta.get("runtime_service", False)),
        source_authority=str(meta.get("source_authority", "")),
        source_ref=str(meta.get("source_ref", "")),
        source_sha=str(meta.get("source_sha", "")),
        source_updated=str(meta.get("source_updated", "")),
        content_hash=str(meta.get("content_hash", "")),
        chunk_type=str(meta.get("chunk_type", "")),
        language=str(meta.get("language", "")),
        symbol=str(meta.get("symbol", "")),
        key=str(meta.get("key", "")),
    )


def _metadata_boost(meta: dict) -> float:
    """Small score nudges for authoritative and recent public sources."""
    boost = 0.0
    lifecycle = str(meta.get("source_lifecycle", "")).lower()
    if lifecycle == "production":
        boost += 0.035
    elif lifecycle in {"active", "accepted"}:
        boost += 0.025
    elif lifecycle == "experimental":
        boost += 0.005
    if str(meta.get("doc_type", "")).lower() in {"adr", "decision", "policy", "ramone-public"}:
        boost += 0.02
    if str(meta.get("source_class", "")).lower() == "curated-public":
        boost += 0.02
    updated = str(meta.get("source_updated") or meta.get("last_updated") or "")
    try:
        parsed = datetime.fromisoformat(updated.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed:
        age_days = max(0, (datetime.now(timezone.utc) - parsed).days)
        if age_days <= 30:
            boost += 0.02
        elif age_days <= 120:
            boost += 0.01
    return boost


def _rank_candidates(
    fused: list[tuple[str, float]],
    cached: dict[str, tuple[str, dict, float]],
    k: int,
) -> list[str]:
    """Apply conservative metadata boosts and keep source diversity."""
    ranked = sorted(
        (
            (cid, score + _metadata_boost(cached[cid][1]))
            for cid, score in fused
            if cid in cached
        ),
        key=lambda item: (-item[1], item[0]),
    )
    selected: list[str] = []
    per_doc: dict[str, int] = {}
    # Give distinct documents a chance to represent the answer before using
    # a second chunk from a document. This prevents a long README from
    # crowding out directly relevant policy or service evidence.
    for cid, _score in ranked:
        meta = cached[cid][1]
        doc_key = str(meta.get("doc_key") or f"{meta.get('source_repo', '')}:{meta.get('file_path', '')}")
        if doc_key in per_doc:
            continue
        selected.append(cid)
        per_doc[doc_key] = 1
        if len(selected) >= k:
            return selected
    # If the corpus has fewer than k documents, fill the remainder while
    # retaining the two-chunk-per-document cap used by answer packing.
    for cid, _score in ranked:
        if cid in selected:
            continue
        meta = cached[cid][1]
        doc_key = str(meta.get("doc_key") or f"{meta.get('source_repo', '')}:{meta.get('file_path', '')}")
        if per_doc.get(doc_key, 0) >= 2:
            continue
        selected.append(cid)
        per_doc[doc_key] = per_doc.get(doc_key, 0) + 1
        if len(selected) >= k:
            break
    return selected


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
    candidate_ids = [cid for cid, _ in fused[: min(max(k * 4, 20), len(fused))]]

    # BM25-only ids never went through the vector query, so their true
    # cosine is not known yet; fetch their stored embeddings and compute
    # it, so every returned score is a real similarity to this query.
    missing = [cid for cid in candidate_ids if cid not in cached]
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
    top_ids = _rank_candidates(fused, cached, k)

    for cid in top_ids:
        entry = cached.get(cid)
        if entry is None:
            continue
        document, meta, similarity = entry
        hits.append(_hit_from(document, meta, similarity))
    return hits


def lexical_search(
    collection: Collection,
    index: HybridIndex,
    query_text: str,
    k: int,
    freshness_marker=None,
) -> list[SearchHit]:
    """Top-k chunks by BM25 alone, for when embedding is unavailable.

    This is the degraded retrieval path. hybrid_search needs a query
    embedding twice over: once for the vector ranking, and again to give
    every returned chunk a true cosine score. Neither is possible while
    Ollama is unreachable, but the BM25 index is built from stored
    documents and needs nothing from Ollama at all, so lexical ranking
    stays available when the embedding step does not.

    Every hit carries score 0.0. The score field on SearchHit is
    documented as a real cosine similarity to the query, and there is no
    query vector here to measure one against. Deriving a number from
    BM25 instead would put a differently-scaled value behind the same
    name, which is worse for a caller than an obviously absent score.
    Callers distinguish this case by the degraded flag on the response
    rather than by inspecting scores.
    """
    total = collection.count()
    if total == 0:
        return []
    index.ensure_fresh(collection, freshness_marker)
    top_ids = index.ranked_ids(query_text, k)
    if not top_ids:
        return []

    fetched = collection.get(ids=top_ids, include=["documents", "metadatas"])
    by_id: dict[str, tuple[str, dict]] = {}
    for position, cid in enumerate(fetched.get("ids", [])):
        by_id[cid] = (fetched["documents"][position], fetched["metadatas"][position])

    hits: list[SearchHit] = []
    for cid in top_ids:
        entry = by_id.get(cid)
        if entry is None:
            continue
        document, meta = entry
        hits.append(_hit_from(document, meta, 0.0))
    return hits
