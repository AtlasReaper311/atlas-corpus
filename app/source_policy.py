"""Public corpus source policy and provenance helpers.

The public/private boundary is strongest when it is enforced before
chunking and embedding. This module turns the Atlas public
classification projection into an allowlist and provides small helpers
for the metadata that search and citations carry downstream.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote


CLASSIFICATION_AUTHORITY = (
    "AtlasReaper311/atlas-infra/policy/public-repository-classifications.json"
)


@dataclass(frozen=True)
class RepoPolicy:
    """One repository entry from the public classification projection."""

    name: str
    full_name: str
    scope: str
    lifecycle: str
    provenance: str
    runtime_service: bool


@dataclass(frozen=True)
class SourceDocument:
    """One approved document ready for chunking."""

    repo: str
    path: str
    doc_type: str
    text: str
    metadata: dict = field(default_factory=dict)


def parse_public_classification(text: str) -> dict[str, RepoPolicy]:
    """Parse the Atlas public classification projection into a repo map."""
    payload = json.loads(text)
    repos: dict[str, RepoPolicy] = {}
    for entry in payload.get("repositories", []):
        full_name = str(entry.get("repository", ""))
        if "/" not in full_name:
            continue
        name = full_name.rsplit("/", 1)[1]
        repos[name] = RepoPolicy(
            name=name,
            full_name=full_name,
            scope=str(entry.get("scope", "")),
            lifecycle=str(entry.get("lifecycle", "")),
            provenance=str(entry.get("provenance", "")),
            runtime_service=bool(entry.get("runtime_service", False)),
        )
    return repos


def content_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def github_blob_url(owner: str, repo: str, path: str, ref: str = "main") -> str:
    quoted_path = "/".join(quote(part) for part in path.replace("\\", "/").split("/"))
    return f"https://github.com/{owner}/{repo}/blob/{quote(ref, safe='')}/{quoted_path}"


def site_public_url(path: str) -> str:
    clean = path.replace("\\", "/")
    if clean.endswith("/index.html"):
        clean = clean[: -len("index.html")]
    elif clean.endswith(".html"):
        clean = clean[: -len(".html")] + "/"
    return "https://atlas-systems.uk/" + clean.lstrip("/")


def source_title(repo: str, path: str, heading: str | None = None) -> str:
    base = f"{repo}/{path}"
    return f"{base} > {heading}" if heading else base


def source_id(repo: str, path: str, chunk_index: int) -> str:
    return f"{repo}/{path}#{chunk_index}"


def repo_metadata(policy: RepoPolicy | None) -> dict:
    """Metadata common to every public-classified repo document."""
    if policy is None:
        return {
            "source_class": "public-classified",
            "source_scope": "public",
            "source_lifecycle": "",
            "source_provenance": "",
            "runtime_service": False,
            "source_authority": CLASSIFICATION_AUTHORITY,
        }
    return {
        "source_class": "public-classified",
        "source_scope": policy.scope,
        "source_lifecycle": policy.lifecycle,
        "source_provenance": policy.provenance,
        "runtime_service": policy.runtime_service,
        "source_authority": CLASSIFICATION_AUTHORITY,
    }


def read_curated_doc(docs_dir: str, filename: str) -> str | None:
    """Read one mounted curated public doc without following path escapes."""
    root = Path(docs_dir).resolve()
    target = (root / filename).resolve()
    if root not in target.parents or not target.is_file():
        return None
    return target.read_text(encoding="utf-8", errors="replace")


def ingest_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
