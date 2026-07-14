"""Architecture decision records as a first-class corpus source.

ADRs live in atlas-infra/docs/adrs/, beside decisions.md, and are
pulled through the GitHub contents API on every ingest. Each record
carries TOML frontmatter (+++ delimited, matching the estate's case
study convention) with an id, date, and status, which become filter
and provenance metadata on every chunk. A malformed record is warned
about and skipped, never indexed, and a missing or unreachable ADR
directory degrades to an empty list so it can never fail an ingest.

The identity line ("ADR-0001 (accepted, 2026-07-02)") is prepended to
every chunk so the record id is lexically searchable: a query for
"ADR-0001" reaches the record through the BM25 half of hybrid search
even though the id carries almost no embedding signal.
"""

from __future__ import annotations

import logging
import re
import tomllib
from datetime import date as date_type
from urllib.parse import urlsplit

import httpx

from app.chunking import Chunk, word_window

logger = logging.getLogger(__name__)

ADR_STATUSES = {"proposed", "accepted", "superseded"}
_ADR_ID_RE = re.compile(r"^ADR-[0-9]{4}$")
_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_SKIP_FILES = {"TEMPLATE.md", "README.md"}
_FRONTMATTER = "+++"
_GITHUB_API = "https://api.github.com"


class AdrError(ValueError):
    """An ADR file is malformed; the message says which field failed."""


def _split_frontmatter(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER:
        raise AdrError("missing +++ frontmatter opening delimiter")
    for position in range(1, len(lines)):
        if lines[position].strip() == _FRONTMATTER:
            block = "\n".join(lines[1:position])
            body = "\n".join(lines[position + 1 :]).strip()
            return block, body
    raise AdrError("frontmatter opened but never closed")


def parse_adr(text: str) -> dict:
    """Validate frontmatter and body; return normalised fields.

    Dates arrive from tomllib as date objects and are normalised to
    strings, because Chroma metadata values must be scalar strings,
    ints, floats, or bools. supersedes is optional and only carried
    when present, so records without it store no null.
    """
    block, body = _split_frontmatter(text)
    try:
        meta = tomllib.loads(block)
    except tomllib.TOMLDecodeError as exc:
        raise AdrError(f"frontmatter is not valid TOML ({exc})") from exc

    adr_id = meta.get("id")
    if not isinstance(adr_id, str) or not _ADR_ID_RE.fullmatch(adr_id):
        raise AdrError("frontmatter 'id' must match ADR-NNNN")
    status = meta.get("status")
    if not isinstance(status, str) or status not in ADR_STATUSES:
        raise AdrError(f"frontmatter 'status' must be one of {sorted(ADR_STATUSES)}")
    raw_date = meta.get("date")
    if isinstance(raw_date, date_type):
        date = raw_date.isoformat()
    elif isinstance(raw_date, str) and _DATE_RE.fullmatch(raw_date):
        try:
            date = date_type.fromisoformat(raw_date).isoformat()
        except ValueError as exc:
            raise AdrError("frontmatter 'date' is not a valid calendar date") from exc
    else:
        raise AdrError("frontmatter 'date' must be an ISO date (YYYY-MM-DD)")
    supersedes = meta.get("supersedes")
    if supersedes is not None:
        if not isinstance(supersedes, str) or not _ADR_ID_RE.fullmatch(supersedes):
            raise AdrError("frontmatter 'supersedes' must match ADR-NNNN")
        if supersedes == adr_id:
            raise AdrError("an ADR cannot supersede itself")
    if not body:
        raise AdrError("ADR body is empty")

    fields = {"id": adr_id, "status": status, "date": date, "body": body}
    if supersedes:
        fields["supersedes"] = supersedes
    return fields


def _base_metadata(fields: dict) -> dict:
    meta = {
        "chunk_type": "adr",
        "adr_id": fields["id"],
        "adr_status": fields["status"],
        "adr_date": fields["date"],
    }
    if "supersedes" in fields:
        meta["adr_supersedes"] = fields["supersedes"]
    return meta


def _sections(body: str) -> list[tuple[str, str]]:
    """Split an ADR body on its ## headings; text before the first is intro."""
    sections: list[tuple[str, str]] = [("", [])]
    for line in body.splitlines():
        if line.startswith("## "):
            sections.append((line[3:].strip(), [line]))
        else:
            sections[-1][1].append(line)
    return [(heading, "\n".join(lines).strip()) for heading, lines in sections]


def chunk_adr(text: str, size: int, overlap: int) -> list[Chunk]:
    """Chunk one ADR: whole when it fits, else per section, id-prefixed."""
    fields = parse_adr(text)
    base = _base_metadata(fields)
    identity = f"{fields['id']} ({fields['status']}, {fields['date']})"
    body = fields["body"]

    whole = f"{identity}\n\n{body}"
    if len(whole.split()) <= size:
        return [Chunk(whole, dict(base))]

    chunks: list[Chunk] = []
    part = 0
    for heading, section in _sections(body):
        if not section:
            continue
        meta = dict(base)
        if heading:
            meta["heading"] = heading
        prefixed = f"{identity}\n\n{section}"
        if len(prefixed.split()) <= size:
            chunks.append(Chunk(prefixed, {**meta, "part": part}))
            part += 1
            continue
        # Window the section alone and re-prefix the identity to every
        # piece, so the record id stays BM25-searchable in continuation
        # chunks; the identity's word cost is taken out of the budget.
        budget = max(1, size - len(identity.split()) - 1)
        for piece in word_window(section, budget, overlap):
            chunks.append(Chunk(f"{identity}\n\n{piece}", {**meta, "part": part}))
            part += 1
    return chunks or [Chunk(f"{identity}\n\n{body}", dict(base))]


async def gather_adrs(
    client: httpx.AsyncClient, settings
) -> list[tuple[str, str, str, str]]:
    """Fetch valid ADRs as deterministic (repo, path, "adr", text) tuples.

    Any GitHub transport, status, or response-shape error returns an empty
    list. That fail-closed behaviour avoids silently indexing a partial ADR
    set. A malformed ADR is a content error rather than a GitHub error and is
    logged and skipped individually.
    """
    owner = settings.github_owner
    repo = settings.adr_repo
    prefix = settings.adr_prefix.strip("/")
    headers = {"User-Agent": "atlas-corpus", "Accept": "application/vnd.github+json"}
    token = getattr(settings, "github_token", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    listing_url = f"{_GITHUB_API}/repos/{owner}/{repo}/contents/{prefix}"
    try:
        response = await client.get(listing_url, headers=headers, timeout=30.0)
        if response.status_code == 404:
            logger.info("no ADR directory at %s/%s/%s yet", owner, repo, prefix)
            return []
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("ADR listing failed for %s/%s: %s", owner, repo, exc)
        return []
    if not isinstance(payload, list):
        logger.warning("ADR listing returned an unexpected payload for %s/%s", owner, repo)
        return []

    documents: list[tuple[str, str, str, str]] = []
    seen_ids: set[str] = set()
    entries = sorted(
        (entry for entry in payload if isinstance(entry, dict)),
        key=lambda entry: str(entry.get("name", "")),
    )
    for entry in entries:
        if entry.get("type") != "file":
            continue
        name = str(entry.get("name", ""))
        if not name.endswith(".md") or name in _SKIP_FILES:
            continue
        download_url = entry.get("download_url")
        if not isinstance(download_url, str):
            logger.warning("ADR entry %s has no download URL", name)
            return []
        parsed_url = urlsplit(download_url)
        if parsed_url.scheme != "https" or parsed_url.netloc != "raw.githubusercontent.com":
            logger.warning("ADR entry %s has an unexpected download host", name)
            return []
        try:
            file_response = await client.get(download_url, headers=headers, timeout=30.0)
            file_response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("ADR fetch failed for %s: %s", name, exc)
            return []

        text = file_response.text
        try:
            fields = parse_adr(text)
        except AdrError as exc:
            logger.warning("skipping malformed ADR %s: %s", name, exc)
            continue
        adr_id = fields["id"]
        stem = name.removesuffix(".md")
        if stem != adr_id and not stem.startswith(f"{adr_id}-"):
            logger.warning("skipping ADR %s: filename does not start with %s", name, adr_id)
            continue
        if adr_id in seen_ids:
            logger.warning("skipping duplicate ADR id %s in %s", adr_id, name)
            continue
        seen_ids.add(adr_id)
        documents.append((repo, f"{prefix}/{name}", "adr", text))

    logger.info("gathered %d ADR(s) from %s/%s", len(documents), owner, repo)
    return documents
