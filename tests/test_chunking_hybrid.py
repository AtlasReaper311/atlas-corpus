from __future__ import annotations

import unittest

from app.chunking import chunk_document
from app.hybrid import HybridIndex, cosine_similarity, rrf_fuse
from app.searcher import hybrid_search


class AmbiguousList(list):
    def __bool__(self):
        raise ValueError("truth value is ambiguous")


class FakeCollection:
    def __init__(self):
        self.ids = ["vector-first", "literal-zone", "other"]
        self.documents = [
            "semantic cloud routing overview",
            "wrangler route uses zone_id and never zone_name",
            "backup retention policy",
        ]
        self.metadatas = [
            {"source_repo": "a", "file_path": "a.md", "doc_type": "doc", "last_updated": "x", "chunk_index": 0},
            {"source_repo": "b", "file_path": "wrangler.toml", "doc_type": "code", "last_updated": "x", "chunk_index": 0},
            {"source_repo": "c", "file_path": "c.md", "doc_type": "doc", "last_updated": "x", "chunk_index": 0},
        ]
        self.embeddings = [[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]]

    def count(self):
        return len(self.ids)

    def get(self, *, include, limit=None, offset=None, ids=None):
        if ids is not None:
            positions = [self.ids.index(cid) for cid in ids]
            return {
                "ids": [self.ids[i] for i in positions],
                "documents": [self.documents[i] for i in positions],
                "metadatas": [self.metadatas[i] for i in positions],
                "embeddings": AmbiguousList([self.embeddings[i] for i in positions]),
            }
        start = offset or 0
        stop = start + (limit or len(self.ids))
        return {
            "ids": self.ids[start:stop],
            "documents": self.documents[start:stop],
        }

    def query(self, *, query_embeddings, n_results, include):
        order = [0, 2, 1][:n_results]
        return {
            "ids": [[self.ids[i] for i in order]],
            "documents": [[self.documents[i] for i in order]],
            "metadatas": [[self.metadatas[i] for i in order]],
            "distances": [[0.0, 0.3, 1.0][:n_results]],
        }


class ChunkingTests(unittest.TestCase):
    def test_python_symbols(self):
        chunks = chunk_document(
            "module.py",
            "import os\n\n\ndef alpha():\n    return 1\n\n\nclass Beta:\n    pass\n",
            "code",
            20,
            2,
        )
        symbols = {chunk.metadata.get("symbol") for chunk in chunks}
        self.assertIn("alpha", symbols)
        self.assertIn("Beta", symbols)

    def test_markdown_headings_do_not_cross(self):
        chunks = chunk_document(
            "README.md",
            "# One\nalpha\n\n# Two\nbeta",
            "readme",
            20,
            2,
        )
        self.assertEqual(["One", "Two"], [chunk.metadata.get("heading") for chunk in chunks])

    def test_json_splits_by_top_level_key(self):
        text = '{"alpha": [' + ",".join('"x"' for _ in range(20)) + '], "beta": 2}'
        chunks = chunk_document("config.json", text, "config", 5, 1)
        self.assertEqual({"alpha", "beta"}, {chunk.metadata.get("key") for chunk in chunks})

    def test_small_json_still_splits_by_key(self):
        chunks = chunk_document("config.json", '{"zone_id": "abc", "name": "demo"}', "config", 512, 64)
        self.assertEqual({"zone_id", "name"}, {chunk.metadata.get("key") for chunk in chunks})

    def test_small_toml_splits_by_table(self):
        chunks = chunk_document(
            "wrangler.toml",
            'name = "demo"\n\n[vars]\nZONE_ID = "abc"\n',
            "config",
            512,
            64,
        )
        self.assertIn("vars", {chunk.metadata.get("key") for chunk in chunks})


class HybridTests(unittest.TestCase):
    def test_rrf_is_deterministic(self):
        expected = rrf_fuse([["b", "a"], ["a", "b"]])
        self.assertEqual(expected, rrf_fuse([["b", "a"], ["a", "b"]]))

    def test_cosine_mismatched_vectors_are_zero(self):
        self.assertEqual(0.0, cosine_similarity([1.0], [1.0, 2.0]))

    def test_exact_identifier_can_be_lifted_by_bm25(self):
        collection = FakeCollection()
        index = HybridIndex()
        hits = hybrid_search(collection, index, [1.0, 0.0], "zone_id", 1, freshness_marker="r1")
        self.assertEqual("wrangler.toml", hits[0].file_path)
        self.assertEqual(0.0, hits[0].score)


if __name__ == "__main__":
    unittest.main()
