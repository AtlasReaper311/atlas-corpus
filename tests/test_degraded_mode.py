"""Locks the behaviour that keeps atlas-corpus useful while Ollama is down.

Before this, an Ollama outage took the service out three separate ways:
startup raised and the container never came up, _run_search let the
embedding error escape as a 500, and the one existing fallback caught
only httpx.TimeoutException, so a refused connection missed it. The BM25
index never needed Ollama at all; it was simply unreachable without
going through the embedding step first.
"""

from __future__ import annotations

import unittest

import httpx

from app.hybrid import HybridIndex
from app.main import _answer_from_hits, _fallback_answer_from_hits
from app.models import SearchHit
from app.searcher import lexical_search


class FakeCollection:
    """Minimal Chroma stand-in covering only what the lexical path uses."""

    def __init__(self, ids=None, documents=None):
        self.ids = ids if ids is not None else ["zone-doc", "backup-doc", "other-doc"]
        self.documents = (
            documents
            if documents is not None
            else [
                "wrangler route uses zone_id and never zone_name",
                "backup retention policy for the vault",
                "unrelated prose about nothing in particular",
            ]
        )
        self.metadatas = [
            {
                "source_repo": f"repo-{i}",
                "file_path": f"file-{i}.md",
                "doc_type": "doc",
                "last_updated": "2026-01-01T00:00:00Z",
                "chunk_index": i,
            }
            for i in range(len(self.ids))
        ]

    def count(self):
        return len(self.ids)

    def get(self, *, include, limit=None, offset=None, ids=None):
        if ids is not None:
            positions = [self.ids.index(cid) for cid in ids]
            return {
                "ids": [self.ids[i] for i in positions],
                "documents": [self.documents[i] for i in positions],
                "metadatas": [self.metadatas[i] for i in positions],
            }
        start = offset or 0
        stop = start + (limit or len(self.ids))
        return {"ids": self.ids[start:stop], "documents": self.documents[start:stop]}

    def query(self, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("lexical_search must not issue a vector query")


def _hit(score: float, text: str = "wrangler route uses zone_id") -> SearchHit:
    return SearchHit(
        text=text,
        score=score,
        source_repo="atlas-infra",
        file_path="docs/decisions.md",
        doc_type="doc",
        last_updated="2026-01-01T00:00:00Z",
        chunk_index=0,
    )


class LexicalSearchTests(unittest.TestCase):
    def test_ranks_without_any_embedding(self):
        collection = FakeCollection()
        hits = lexical_search(collection, HybridIndex(), "zone_name wrangler", 3)
        self.assertTrue(hits)
        self.assertEqual(hits[0].file_path, "file-0.md")

    def test_every_score_is_zero_rather_than_a_fake_cosine(self):
        collection = FakeCollection()
        hits = lexical_search(collection, HybridIndex(), "zone_name wrangler", 3)
        self.assertTrue(all(hit.score == 0.0 for hit in hits))

    def test_empty_collection_returns_nothing(self):
        collection = FakeCollection(ids=[], documents=[])
        self.assertEqual(lexical_search(collection, HybridIndex(), "anything", 3), [])

    def test_query_with_no_lexical_overlap_returns_nothing(self):
        collection = FakeCollection()
        hits = lexical_search(collection, HybridIndex(), "zzzzqqqq", 3)
        self.assertEqual(hits, [])


class FallbackAnswerTests(unittest.TestCase):
    def test_unavailable_keeps_excerpts_despite_zero_scores(self):
        # lexical hits always score 0.0, so the timeout path's 0.5 cosine
        # threshold would throw away every usable result.
        answer = _fallback_answer_from_hits([_hit(0.0)], unavailable=True)
        self.assertTrue(answer.degraded)
        self.assertTrue(answer.sources)
        self.assertIn("not a synthesized answer", answer.answer)

    def test_timeout_path_still_suppresses_weak_matches(self):
        answer = _fallback_answer_from_hits([_hit(0.1)])
        self.assertFalse(answer.degraded)
        self.assertEqual(answer.sources, [])

    def test_timeout_path_still_answers_on_strong_matches(self):
        answer = _fallback_answer_from_hits([_hit(0.9)])
        self.assertFalse(answer.degraded)
        self.assertTrue(answer.sources)
        self.assertIn("public request timeout", answer.answer)

    def test_no_hits_reports_nothing_found(self):
        answer = _fallback_answer_from_hits([], unavailable=True)
        self.assertEqual(answer.sources, [])
        self.assertTrue(answer.degraded)


class ExplodingClient:
    """Any outbound call here means the degraded short-circuit was missed."""

    async def post(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("synthesis must not be attempted while degraded")


class AnswerFromHitsTests(unittest.IsolatedAsyncioTestCase):
    async def test_degraded_skips_the_doomed_synthesis_call(self):
        answer = await _answer_from_hits(
            ExplodingClient(), None, "why 522", [_hit(0.0)], degraded=True
        )
        self.assertTrue(answer.degraded)
        self.assertTrue(answer.sources)

    async def test_connection_error_degrades_instead_of_raising(self):
        class RefusingClient:
            async def post(self, *args, **kwargs):
                raise httpx.ConnectError("connection refused")

        answer = await _answer_from_hits(
            RefusingClient(), _Settings(), "why 522", [_hit(0.8)]
        )
        self.assertTrue(answer.degraded)
        self.assertIn("answer model is unavailable", answer.answer)

    async def test_timeout_keeps_its_own_wording(self):
        class SlowClient:
            async def post(self, *args, **kwargs):
                raise httpx.ReadTimeout("too slow")

        answer = await _answer_from_hits(
            SlowClient(), _Settings(), "why 522", [_hit(0.8)]
        )
        self.assertFalse(answer.degraded)
        self.assertIn("public request timeout", answer.answer)


class _Settings:
    """Only the attributes _answer_from_hits reads before its request."""

    ollama_host = "http://127.0.0.1:1"
    answer_model = "test-model"
    answer_timeout_seconds = 5.0


if __name__ == "__main__":
    unittest.main()


class EmbedderPlacementTests(unittest.IsolatedAsyncioTestCase):
    """The embedder must not quietly move back onto the GPU.

    On SPECULAR-CORE the answer model and the embedder cannot both be
    resident, so an embedder that claims GPU memory evicts the answer
    model on every query and each answer pays a full reload. This is a
    performance contract, not a style preference, so it is pinned here.
    """

    async def test_embed_request_sends_the_configured_gpu_layers(self):
        captured = {}

        class CapturingClient:
            async def post(self, url, json=None, timeout=None):
                captured.update(json or {})

                class Response:
                    @staticmethod
                    def raise_for_status():
                        return None

                    @staticmethod
                    def json():
                        return {"embeddings": [[0.1, 0.2]]}

                return Response()

        from app.embedder import embed_query

        class _S:
            ollama_host = "http://127.0.0.1:11434"
            embed_model = "nomic-embed-text"
            embed_batch_size = 16
            embed_num_gpu = 0
            embed_timeout_seconds = 5.0

        await embed_query(CapturingClient(), _S(), "a query")
        self.assertEqual(captured.get("options", {}).get("num_gpu"), 0)

    def test_default_keeps_the_embedder_off_the_gpu(self):
        from app.config import Settings

        self.assertEqual(Settings.model_fields["embed_num_gpu"].default, 0)
