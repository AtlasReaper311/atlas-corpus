"""Lexical retrieval and rank fusion for the corpus.

Vector search alone misses exact identifiers. A query for "zone_id" or
"522" wants the chunk that contains that literal token, but cosine
similarity over nomic-embed-text ranks by meaning, and a rare literal
carries little of it. BM25 ranks by term overlap and finds those hits;
fusing the two rankings keeps the strengths of both.

The BM25 index lives in memory, rebuilt from Chroma in one paginated
pass. At this corpus scale (tens of documents, low thousands of
chunks) the rebuild is trivial, so staleness is handled by rebuilding
whenever the collection changes rather than by any coordination
between the ingest path and the request path.
"""

from __future__ import annotations

import math
import re
import threading

from rank_bm25 import BM25Okapi

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_TOKEN = re.compile(r"[a-z0-9]+")

_PAGE = 500


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, with camelCase and snake_case split.

    camelCase is broken at the case boundary and snake_case falls out
    of the alphanumeric run split, so zoneId, zone_id, and "zone id"
    all tokenize to ["zone", "id"]. A query for an identifier then
    matches the same identifier however it was cased in the source.
    """
    spaced = _CAMEL_BOUNDARY.sub(" ", text)
    return _TOKEN.findall(spaced.lower())


def cosine_similarity(a, b) -> float:
    """Cosine similarity; 0.0 for zero or mismatched vectors."""
    if len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for left, right in zip(a, b):
        left = float(left)
        right = float(right)
        dot += left * right
        norm_a += left * left
        norm_b += right * right
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / math.sqrt(norm_a * norm_b)


def rrf_fuse(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal rank fusion of several ranked id lists, best first.

    RRF sums 1 / (k + rank) across rankings, so an id ranked highly by
    either retriever rises without any comparison between their scores.
    That matters here because cosine similarity and BM25 scores live on
    different, incomparable scales; a weighted blend would need a
    normalisation that has no principled value. k is 60 following
    Cormack, Clarke, and Buettcher, whose value is a well-worn default
    rather than a tuned estate constant. Ties break on the id so the
    order is deterministic.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


class HybridIndex:
    """In-memory BM25 index over the collection, self-healing on drift.

    ensure_fresh rebuilds when the collection's chunk count changes or
    when a freshness marker (the last-refresh timestamp) changes. The
    count alone would miss a re-ingest that replaced content without
    changing the total; the marker closes that gap. Rebuilds run under
    a lock so a single-worker uvicorn never serves a half-built index.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ids: list[str] = []
        self._bm25: BM25Okapi | None = None
        self._token_sets: list[set[str]] = []
        self._built_count = -1
        self._built_marker: object | None = object()

    def ensure_fresh(self, collection, marker=None) -> None:
        with self._lock:
            count = collection.count()
            if count == self._built_count and marker == self._built_marker:
                return
            self._rebuild(collection, count, marker)

    def _rebuild(self, collection, count: int, marker) -> None:
        ids: list[str] = []
        documents: list[str] = []
        offset = 0
        while offset < count:
            batch = collection.get(include=["documents"], limit=_PAGE, offset=offset)
            batch_ids = batch.get("ids") or []
            batch_docs = batch.get("documents") or []
            if not batch_ids:
                break
            ids.extend(batch_ids)
            documents.extend(batch_docs)
            offset += len(batch_ids)
        # BM25Okapi divides by the mean document length, so a corpus of
        # only-empty token lists would raise; empties are dropped before
        # the index is built, and an all-empty corpus leaves it unbuilt.
        usable = [
            (cid, tokens)
            for cid, document in zip(ids, documents)
            for tokens in (tokenize(document or ""),)
            if tokens
        ]
        if usable:
            self._ids = [cid for cid, _ in usable]
            token_lists = [tokens for _, tokens in usable]
            self._token_sets = [set(tokens) for tokens in token_lists]
            self._bm25 = BM25Okapi(token_lists)
        else:
            self._ids = []
            self._token_sets = []
            self._bm25 = None
        self._built_count = count
        self._built_marker = marker

    def ranked_ids(self, query_text: str, k: int) -> list[str]:
        """Top-k chunk ids by BM25 among documents with lexical overlap."""
        with self._lock:
            bm25 = self._bm25
            ids = list(self._ids)
            token_sets = list(self._token_sets)
        if bm25 is None:
            return []
        tokens = tokenize(query_text)
        if not tokens:
            return []
        scores = bm25.get_scores(tokens)
        query_terms = set(tokens)
        ranked = sorted(
            (
                (cid, float(score))
                for cid, score, doc_terms in zip(ids, scores, token_sets)
                if query_terms.intersection(doc_terms)
            ),
            key=lambda item: (-item[1], item[0]),
        )
        return [cid for cid, _ in ranked[:k]]
