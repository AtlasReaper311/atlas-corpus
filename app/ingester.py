"""Document ingestion: GitHub sources, local docs, chunking, upsert.

Sources, in ingest order:
  1. Every non-fork, non-archived repo's README (doc_type: readme)
  2. Pinned extra files, e.g. atlas-infra decisions.md (doc_type: decision)
  3. Site HTML under work/ and writing/ (case-study / article)
  4. Local files mounted at /srv/docs (doc_type: doc), for the brand
     and context documents that live outside any public repo

Chunk ids are deterministic (sha1 of repo:path:index), so re-ingest is
an upsert: unchanged chunks overwrite themselves, and any chunk index
beyond the document's new length is deleted. The corpus therefore
converges on the truth of the sources rather than accreting history.
"""

import hashlib
import json
import logging
import time
from base64 import b64decode
from html.parser import HTMLParser
from pathlib import Path

import httpx
from chromadb.api.models.Collection import Collection

from app.adr import gather_adrs
from app.chunking import chunk_document
from app.config import Settings

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


class IngestStats(dict):
    """Counters for one ingest pass; a dict so it JSON-serialises as-is."""


# --------------------------------------------------------------------- #
# GitHub access                                                           #
# --------------------------------------------------------------------- #


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
        """All of an owner's public repos, paginated."""
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
        """One file's text via the contents API, or None when absent."""
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
        """Paths of .html files under a prefix, via the recursive tree."""
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


# --------------------------------------------------------------------- #
# HTML to text                                                            #
# --------------------------------------------------------------------- #


class _TextExtractor(HTMLParser):
    """Stdlib HTML-to-text: body copy in, chrome out.

    script/style/nav/footer subtrees are skipped because navigation and
    boilerplate would otherwise dominate every page's embedding and
    make unrelated case studies look similar.
    """

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
    """Reduce an HTML document to searchable plain text."""
    extractor = _TextExtractor()
    extractor.feed(html)
    return extractor.text()


# --------------------------------------------------------------------- #
# Chunking                                                                #
# --------------------------------------------------------------------- #


def chunk_words(text: str, size: int, overlap: int) -> list[str]:
    """Word-window chunking with overlap.

    Word counts approximate token counts closely enough for retrieval
    without buying a tokenizer dependency; the embedding model's 8k
    window has an order of magnitude of headroom over these chunks.
    """
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


# --------------------------------------------------------------------- #
# Ingest                                                                  #
# --------------------------------------------------------------------- #


def _doc_key(repo: str, path: str) -> str:
    """Stable identity for one source document."""
    return f"{repo}:{path}"


def _chunk_id(repo: str, path: str, index: int) -> str:
    """Deterministic chunk id so re-ingest upserts instead of duplicating."""
    return hashlib.sha1(f"{repo}:{path}:{index}".encode()).hexdigest()


async def _gather_documents(
    gh: GitHub, settings: Settings
) -> list[tuple[str, str, str, str]]:
    """Collect (repo, path, doc_type, text) for every source."""
    documents: list[tuple[str, str, str, str]] = []
    owner = settings.github_owner
    excluded = {name.strip() for name in settings.exclude_repos.split(",") if name.strip()}

    # 1. READMEs across the estate
    for repo in await gh.list_repos(owner):
        name = repo["name"]
        if name in excluded or repo.get("fork") or repo.get("archived"):
            continue
        readme = await gh.get_file(owner, name, "README.md")
        if readme:
            documents.append((name, "README.md", "readme", readme))

    # 2. Pinned extra files (decisions.md and friends)
    for entry in settings.extra_files.split(","):
        entry = entry.strip()
        if not entry:
            continue
        repo, path, doc_type = entry.split(":", 2)
        text = await gh.get_file(owner, repo, path)
        if text:
            documents.append((repo, path, doc_type, text))
        else:
            logger.warning("extra file missing on GitHub: %s/%s", repo, path)

    # 3. Site HTML: case studies and articles
    for prefix, doc_type in (
        (settings.case_study_prefix, "case-study"),
        (settings.article_prefix, "article"),
    ):
        for path in await gh.list_html_under(owner, settings.site_repo, prefix):
            html = await gh.get_file(owner, settings.site_repo, path)
            if html:
                documents.append((settings.site_repo, path, doc_type, html_to_text(html)))

    # 4. Local docs (brand doc, context doc) mounted read-only
    docs_dir = Path(settings.docs_dir)
    if docs_dir.is_dir():
        for path in sorted(docs_dir.glob("*.md")):
            documents.append(("local", path.name, "doc", path.read_text(errors="replace")))

    return documents


async def run_ingest(
    client: httpx.AsyncClient,
    settings: Settings,
    collection: Collection,
    embed_fn,
) -> IngestStats:
    """Full ingest pass: fetch, chunk, embed, upsert, prune stale chunks.

    embed_fn is injected (rather than importing the embedder) so tests
    can exercise ingestion without an Ollama on the network.
    """
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
        # Prune chunks beyond the document's new length (doc shrank).
        existing = collection.get(where={"doc_key": _doc_key(repo, path)})
        stale = [cid for cid in existing["ids"] if cid not in set(ids)]
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

    stats["took_s"] = round(time.time() - started, 1)
    stats["index"] = index
    logger.info("ingest complete: %s", json.dumps({k: v for k, v in stats.items() if k != "index"}))
    return stats
