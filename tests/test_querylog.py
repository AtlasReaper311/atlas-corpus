"""Tests for the query log; pure stdlib, temp database per test."""

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from app.index_state import restore_index_from_collection
from app import querylog


class QueryLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "queries.db")
        self.addCleanup(self.tmp.cleanup)

    def test_roundtrip_counts(self):
        querylog.log_query(self.db, "how does the tunnel work", 3, 40)
        querylog.log_query(self.db, "tunnel portproxy drift", 2, 35)
        s = querylog.stats(self.db)
        self.assertEqual(s["queries_total"], 2)
        self.assertEqual(s["queries_last_hour"], 2)
        self.assertEqual(s["queries_today"], 2)
        self.assertIsNotNone(s["last_query_at"])

    def test_window_summary_stopwords_and_ranking(self):
        for q in ("the tunnel", "tunnel drift", "what is the tunnel"):
            querylog.log_query(self.db, q, 1, 10)
        now = int(time.time())
        summary = querylog.window_summary(self.db, now - 60, now + 2)
        self.assertEqual(summary["count"], 3)
        self.assertEqual(summary["top_terms"][0], {"term": "tunnel", "count": 3})
        terms = [t["term"] for t in summary["top_terms"]]
        self.assertNotIn("the", terms)
        self.assertNotIn("what", terms)

    def test_query_text_capped_at_500_chars(self):
        querylog.log_query(self.db, "x" * 900, 0, 5)
        con = sqlite3.connect(self.db)
        stored = con.execute("SELECT query FROM queries").fetchone()[0]
        con.close()
        self.assertEqual(len(stored), 500)

    def test_empty_window_is_zero_not_error(self):
        summary = querylog.window_summary(self.db, 0, 1)
        self.assertEqual(summary, {"count": 0, "top_terms": []})

    def test_unwritable_path_degrades_instead_of_raising(self):
        bad = "/proc/definitely/not/writable/queries.db"
        querylog.log_query(bad, "q", 0, 1)  # must not raise
        self.assertEqual(querylog.stats(bad)["queries_total"], 0)
        self.assertEqual(querylog.window_summary(bad, 0, 1)["count"], 0)


class FakeCollection:
    def get(self, include=None):
        return {
            "metadatas": [
                {
                    "doc_key": "repo:README.md",
                    "source_repo": "repo",
                    "file_path": "README.md",
                    "doc_type": "readme",
                    "last_updated": "2026-07-07T09:00:00Z",
                },
                {
                    "doc_key": "repo:README.md",
                    "source_repo": "repo",
                    "file_path": "README.md",
                    "doc_type": "readme",
                    "last_updated": "2026-07-07T09:01:00Z",
                },
            ]
        }


class StartupIndexTests(unittest.TestCase):
    def test_restore_index_from_persisted_metadata(self):
        index = restore_index_from_collection(FakeCollection())
        self.assertEqual(len(index), 1)
        self.assertEqual(index["repo:README.md"]["chunks"], 2)
        self.assertEqual(index["repo:README.md"]["last_updated"], "2026-07-07T09:01:00Z")
