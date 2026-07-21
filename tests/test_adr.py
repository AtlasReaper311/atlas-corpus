from __future__ import annotations

import unittest
from types import SimpleNamespace

import httpx

from app.adr import AdrError, chunk_adr, gather_adrs, parse_adr
from app.chunking import chunk_document


VALID = """+++
id = "ADR-0001"
date = 2026-07-02
status = "accepted"
+++

# ADR-0001: Test

## Context

Context.

## Decision

Decision.

## Consequences

Consequences.
"""

LEGACY = """+++
id = "ADR-0003"
date = 2026-07-20
status = "accepted"
slug = "public-private-estate-boundary"
visibility = "public"
repositories = []
services = []
contracts = []
policies = []
+++

# ADR-0003: Public and private estate boundary

## Context

Context.

## Decision

Decision.

## Consequences

Consequences.
"""


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://example.invalid")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)

    async def get(self, *args, **kwargs):
        return self.responses.pop(0)


class AdrTests(unittest.IsolatedAsyncioTestCase):
    def settings(self):
        return SimpleNamespace(
            github_owner="AtlasReaper311",
            github_token="",
            adr_repo="atlas-infra",
            adr_prefix="docs/adrs",
        )

    def test_parse_and_chunk(self):
        fields = parse_adr(VALID)
        self.assertEqual("ADR-0001", fields["id"])
        chunks = chunk_adr(VALID, 12, 2)
        self.assertTrue(all(chunk.text.startswith("ADR-0001") for chunk in chunks))

    def test_parse_legacy_slug(self):
        fields = parse_adr(LEGACY)
        self.assertEqual("ADR-0003", fields["id"])
        self.assertEqual("public-private-estate-boundary", fields["slug"])
        chunks = chunk_adr(LEGACY, 100, 10)
        self.assertEqual("public-private-estate-boundary", chunks[0].metadata["adr_slug"])

    def test_bad_slug_is_rejected(self):
        with self.assertRaises(AdrError):
            parse_adr(LEGACY.replace("public-private-estate-boundary", "Bad Slug", 1))

    def test_bad_id_is_rejected(self):
        with self.assertRaises(AdrError):
            parse_adr(VALID.replace('ADR-0001', 'adr-one', 1))

    def test_invalid_calendar_date_is_rejected(self):
        with self.assertRaises(AdrError):
            parse_adr(VALID.replace("2026-07-02", '"2026-99-99"'))

    def test_chunk_document_dispatches_adr(self):
        chunks = chunk_document("ADR-0001-test.md", VALID, "adr", 100, 10)
        self.assertEqual("adr", chunks[0].metadata["chunk_type"])

    async def test_github_error_returns_empty(self):
        client = FakeClient([FakeResponse(status_code=500)])
        self.assertEqual([], await gather_adrs(client, self.settings()))

    async def test_partial_fetch_failure_returns_empty(self):
        listing = [
            {"type": "file", "name": "ADR-0001-a.md", "download_url": "https://raw.githubusercontent.com/x/y/main/a"},
            {"type": "file", "name": "ADR-0002-b.md", "download_url": "https://raw.githubusercontent.com/x/y/main/b"},
        ]
        client = FakeClient([
            FakeResponse(payload=listing),
            FakeResponse(text=VALID),
            FakeResponse(status_code=500),
        ])
        self.assertEqual([], await gather_adrs(client, self.settings()))

    async def test_listing_is_sorted(self):
        listing = [
            {"type": "file", "name": "ADR-0002-b.md", "download_url": "https://raw.githubusercontent.com/x/y/main/b"},
            {"type": "file", "name": "ADR-0001-a.md", "download_url": "https://raw.githubusercontent.com/x/y/main/a"},
        ]
        second = VALID.replace("ADR-0001", "ADR-0002")
        client = FakeClient([
            FakeResponse(payload=listing),
            FakeResponse(text=VALID),
            FakeResponse(text=second),
        ])
        docs = await gather_adrs(client, self.settings())
        self.assertEqual(
            ["docs/adrs/ADR-0001-a.md", "docs/adrs/ADR-0002-b.md"],
            [doc[1] for doc in docs],
        )

    async def test_legacy_slug_allows_stable_non_numbered_path(self):
        listing = [{
            "type": "file",
            "name": "public-private-estate-boundary.md",
            "download_url": "https://raw.githubusercontent.com/x/y/main/boundary",
        }]
        client = FakeClient([FakeResponse(payload=listing), FakeResponse(text=LEGACY)])
        docs = await gather_adrs(client, self.settings())
        self.assertEqual(
            ["docs/adrs/public-private-estate-boundary.md"],
            [doc[1] for doc in docs],
        )

    async def test_legacy_filename_without_matching_slug_is_skipped(self):
        listing = [{
            "type": "file",
            "name": "another-boundary.md",
            "download_url": "https://raw.githubusercontent.com/x/y/main/boundary",
        }]
        client = FakeClient([FakeResponse(payload=listing), FakeResponse(text=LEGACY)])
        self.assertEqual([], await gather_adrs(client, self.settings()))


if __name__ == "__main__":
    unittest.main()
