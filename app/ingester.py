"""Public-source document ingestion for the Atlas Systems corpus.

Sources, in ingest order:
  1. Every non-fork, non-archived public repository README
  2. Explicit pinned files from public repositories
  3. Published site HTML under work/ and writing/
  4. Public architecture decision records

Local mounted context documents are intentionally not ingested. The corpus is a
public projection, so authenticated or owner-local material must never become a
search source merely because it is available on the host.

Chunk ids are deterministic. Each refresh also removes chunks whose source
document is no longer in the approved source set, so tightening the publication
boundary removes old material instead of leaving it stranded in Chroma.
"""

import hashlib
import json
import logging
import time
from base64 import b64decode
from html.parser import HTMLParser

import httpx
from chromadb.api.models.Collection import Collection

from app.adr import gather_adrs
from app.chunking import chunk_document
from app.config import Settings

logger = logging.getLogger(__name__)
GITHUB_API = "https://api.github.com"


class IngestStats(dict):
    """Counters for one ingest pass; a dict so it JSON-serialises as-is."""


class GitHub:
    """Minimal async GitHub client for public-content ingestion."""

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._headers = {
            "accept": "application/vnd.github+json",
            "x-github-api-version": "2022-11-28",
            "user-agent": "atlas-corpus/1.0",
        }
        if settings.github_token:
            self._headers["authorization"] = f"Bearer {settings.github_token}"

    async def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        response = await self._client.get(
            f"{GITHUB_API}{path}", headers=self._headers, params=params, timeout=30.0
        )
        response.raise_for_status()
        return response

    async def list_repos(self, owner: str) -> list[dict]:
        """All public repositories for an owner, paginated."""
        repos: list[dict] = []
        page = 1
        while True:
            response = await self._get(
                f"/users/{owner}/repos",
                params={"per_page": 100, "page": page, "sort": "full_name"},
            )
            batch = response.json()
            repos.extend(batch)
            if len(batch) < 100:
                return repos
            page += 1

    async def get_file(self, owner: str, repo: str, path: str) -> str | None:
        """One public file's text via the contents API, or None when absent."""
        try:
            response = await self._get(f"/repos/{owner}/{repo}/contents/{path}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        payload = response.json()
        if payload.get("encoding") != "base64":
            return None
        return b64decode(payload["content"]).decode("utf-8", errors="replace")

    async def list_html_under(self, owner: str, repo: str, prefix: str) -> list[str]:
        """Paths of public HTML files under a prefix, via the recursive tree."""
        try:
            response = await self._get(
                f"/repos/{owner}/{repo}/git/trees/main", params={"recursive": "1"}
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return []
            raise
        return [
            node["path"]
            for node in response.json().get("tree", [])
            if node.get("type") == "blob"
            and node["path"].startswith(prefix)
            and node["path"].endswith(".html")
        ]


class _TextExtractor(HTMLParser):
    """Reduce public site HTML to searchable body text."""

    _SKIP = {"script", "style", "nav", "footer", "noscript", "svg", "head"}
    _BREAK = {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3", "h4", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BREAK:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in self._BREAK:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        lines = [" ".join(line.split()) for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)


def html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    return extractor.text()


def chunk_words(text: str, size: int, overlap: int) -> list[str]:
    """Legacy word-window helper retained for compatibility with tests."""
    words = text.split()
    if not words:
        return []
    if len(words) <= size:
        return [" ".join(words)]
    step = max(1, size - overlap)
    chunks = []
    for start in range(0, len(words), step):
        window = words[start : start + size]
        chunks.append(" ".join(window))
        if start + size >= len(words):
            break
    return chunks


def _doc_key(repo: str, path: str) -> str:
    return f"{repo}:{path}"


def _chunk_id(repo: str, path: str, index: int) -> str:
    return hashlib.sha1(f"{repo}:{path}:{index}".encode()).hexdigest()


async def _gather_documents(
    gh: GitHub, settings: Settings
) -> list[tuple[str, str, str, str]]:
    """Collect only approved public source documents."""
    documents: list[tuple[str, str, str, str]] = []
    owner = settings.github_owner
    excluded = {name.strip() for name in settings.exclude_repos.split(",") if name.strip()}

    for repo in await gh.list_repos(owner):
        name = repo["name"]
        if name in excluded or repo.get("fork") or repo.get("archived") or repo.get("private"):
            continue
        readme = await gh.get_file(owner, name, "README.md")
        if readme:
            documents.append((name, "README.md", "readme", readme))

    for entry in settings.extra_files.split(","):
        entry = entry.strip()
        if not entry:
            continue
        repo, path, doc_type = entry.split(":", 2)
        text = await gh.get_file(owner, repo, path)
        if text:
            documents.append((repo, path, doc_type, text))
        else:
            logger.warning("extra public file missing on GitHub: %s/%s", repo, path)

    for prefix, doc_type in (
        (settings.case_study_prefix, "case-study"),
        (settings.article_prefix, "article"),
    ):
        for path in await gh.list_html_under(owner, settings.site_repo, prefix):
            html = await gh.get_file(owner, settings.site_repo, path)
            if html:
                documents.append((settings.site_repo, path, doc_type, html_to_text(html)))

    return documents


def _prune_removed_documents(
    collection: Collection,
    active_doc_keys: set[str],
) -> int:
    """Delete chunks whose source document left the approved public source set."""
    existing = collection.get(include=["metadatas"])
    stale_ids: list[str] = []
    ids = existing.get("ids") or []
    metadatas = existing.get("metadatas") or []
    for chunk_id, metadata in zip(ids, metadatas):
        doc_key = metadata.get("doc_key") if isinstance(metadata, dict) else None
        if not isinstance(doc_key, str) or doc_key not in active_doc_keys:
            stale_ids.append(chunk_id)
    if stale_ids:
        collection.delete(ids=stale_ids)
    return len(stale_ids)


async def run_ingest(
    client: httpx.AsyncClient,
    settings: Settings,
    collection: Collection,
    embed_fn,
) -> IngestStats:
    """Full public-source ingest pass with deterministic upsert and pruning."""
    started = time.time()
    gh = GitHub(client, settings)
    documents = await _gather_documents(gh, settings)
    documents.extend(await gather_adrs(client, settings))
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    stats = IngestStats(documents=0, chunks=0, deleted=0, skipped=0)
    index: dict[str, dict] = {}

    for repo, path, doc_type, text in documents:
        chunk_objs = chunk_document(
            path, text, doc_type, settings.chunk_words, settings.chunk_overlap_words
        )
        chunks = [chunk.text for chunk in chunk_objs]
        if not chunks:
            stats["skipped"] += 1
            continue
        ids = [_chunk_id(repo, path, i) for i in range(len(chunks))]
        embeddings = await embed_fn(client, settings, chunks)
        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=[
                {
                    "doc_key": _doc_key(repo, path),
                    "source_repo": repo,
                    "file_path": path,
                    "doc_type": doc_type,
                    "last_updated": now_iso,
                    "chunk_index": i,
                    **chunk_objs[i].metadata,
                }
                for i in range(len(chunks))
            ],
        )
        existing = collection.get(where={"doc_key": _doc_key(repo, path)})
        stale = [chunk_id for chunk_id in existing["ids"] if chunk_id not in set(ids)]
        if stale:
            collection.delete(ids=stale)
            stats["deleted"] += len(stale)

        stats["documents"] += 1
        stats["chunks"] += len(chunks)
        index[_doc_key(repo, path)] = {
            "source_repo": repo,
            "file_path": path,
            "doc_type": doc_type,
            "chunks": len(chunks),
            "last_updated": now_iso,
        }
        logger.info("ingested %s/%s: %d chunks (%s)", repo, path, len(chunks), doc_type)

    removed = _prune_removed_documents(collection, set(index))
    stats["deleted"] += removed
    if removed:
        logger.info("pruned %d chunks from sources outside the public source set", removed)

    stats["took_s"] = round(time.time() - started, 1)
    stats["index"] = index
    logger.info(
        "public ingest complete: %s",
        json.dumps({key: value for key, value in stats.items() if key != "index"}),
    )
    return stats
