from __future__ import annotations

import unittest

from app.chunking import chunk_document
from app.models import SearchHit
from app.searcher import hybrid_search
from app.source_policy import (
    CLASSIFICATION_AUTHORITY,
    github_blob_url,
    parse_public_classification,
    repo_metadata,
    site_public_url,
)


class SourcePolicyTests(unittest.TestCase):
    def test_public_classification_projection_is_the_allowlist(self):
        repos = parse_public_classification(
            """
            {
              "repositories": [
                {
                  "repository": "AtlasReaper311/ramone-edge",
                  "scope": "internal",
                  "lifecycle": "production",
                  "provenance": "original",
                  "runtime_service": true
                }
              ]
            }
            """
        )

        self.assertEqual(["ramone-edge"], sorted(repos))
        meta = repo_metadata(repos["ramone-edge"])
        self.assertEqual(meta["source_class"], "public-classified")
        self.assertEqual(meta["source_scope"], "internal")
        self.assertEqual(meta["source_lifecycle"], "production")
        self.assertTrue(meta["runtime_service"])
        self.assertEqual(meta["source_authority"], CLASSIFICATION_AUTHORITY)

    def test_source_urls_are_stable_for_github_and_site_pages(self):
        self.assertEqual(
            github_blob_url("AtlasReaper311", "atlas-corpus", "docs/ramone-public-context.md"),
            "https://github.com/AtlasReaper311/atlas-corpus/blob/main/docs/ramone-public-context.md",
        )
        self.assertEqual(
            site_public_url("writing/ramone-local-ai-system/index.html"),
            "https://atlas-systems.uk/writing/ramone-local-ai-system/",
        )


class MetadataRankingTests(unittest.TestCase):
    def test_heading_path_is_preserved_for_nested_markdown(self):
        chunks = chunk_document(
            "README.md",
            "# Ramone\nintro\n\n## Public Path\nuses corpus",
            "readme",
            20,
            2,
        )

        self.assertEqual("Ramone > Public Path", chunks[1].metadata["heading_path"])

    def test_hybrid_search_carries_rich_metadata(self):
        collection = _FakeCollection()
        hits = hybrid_search(collection, _FakeIndex(), [1.0, 0.0], "ramone path", 1)

        self.assertEqual(1, len(hits))
        hit = hits[0]
        self.assertIsInstance(hit, SearchHit)
        self.assertEqual("atlas-corpus/docs/ramone-public-context.md#0", hit.id)
        self.assertEqual("curated-public", hit.source_class)
        self.assertEqual("Ramone > Public Path", hit.heading_path)
        self.assertEqual(
            "https://github.com/AtlasReaper311/atlas-corpus/blob/main/docs/ramone-public-context.md",
            hit.public_url,
        )


class _FakeCollection:
    ids = ["ramone-doc"]
    documents = ["Public Ramone uses ramone-edge to reach atlas-corpus."]
    metadatas = [
        {
            "source_repo": "atlas-corpus",
            "file_path": "docs/ramone-public-context.md",
            "doc_type": "ramone-public",
            "last_updated": "2026-08-31T00:00:00Z",
            "chunk_index": 0,
            "source_id": "atlas-corpus/docs/ramone-public-context.md#0",
            "source_title": "atlas-corpus/docs/ramone-public-context.md > Ramone > Public Path",
            "source_class": "curated-public",
            "source_scope": "public",
            "source_lifecycle": "production",
            "runtime_service": True,
            "heading": "Public Path",
            "heading_path": "Ramone > Public Path",
            "public_url": "https://github.com/AtlasReaper311/atlas-corpus/blob/main/docs/ramone-public-context.md",
        }
    ]
    embeddings = [[1.0, 0.0]]

    def count(self):
        return 1

    def query(self, *, query_embeddings, n_results, include):
        return {
            "ids": [self.ids],
            "documents": [self.documents],
            "metadatas": [self.metadatas],
            "distances": [[0.0]],
        }


class _FakeIndex:
    def ensure_fresh(self, collection, freshness_marker=None):
        return None

    def ranked_ids(self, query_text, limit):
        return ["ramone-doc"]


if __name__ == "__main__":
    unittest.main()
