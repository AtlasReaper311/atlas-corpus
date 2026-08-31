"""Helpers for rebuilding the in-memory corpus index from stored metadata."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def restore_index_from_collection(collection) -> dict[str, dict]:
    """Rebuild the in-memory /index from persisted Chroma metadata."""
    try:
        rows = collection.get(include=["metadatas"])
    except Exception:  # noqa: BLE001
        logger.exception("could not restore corpus index from Chroma")
        return {}
    index: dict[str, dict] = {}
    for meta in rows.get("metadatas") or []:
        if not meta:
            continue
        key = str(meta.get("doc_key") or f"{meta.get('source_repo')}:{meta.get('file_path')}")
        entry = index.setdefault(key, _entry_from_metadata(meta))
        entry["chunks"] += 1
        if str(meta.get("last_updated", "")) > entry["last_updated"]:
            entry["last_updated"] = str(meta.get("last_updated", ""))
    return index


def _entry_from_metadata(meta: dict) -> dict:
    return {
        "source_repo": str(meta.get("source_repo", "")),
        "file_path": str(meta.get("file_path", "")),
        "doc_type": str(meta.get("doc_type", "")),
        "chunks": 0,
        "last_updated": str(meta.get("last_updated", "")),
        "source_class": str(meta.get("source_class", "")),
        "source_scope": str(meta.get("source_scope", "")),
        "source_lifecycle": str(meta.get("source_lifecycle", "")),
        "runtime_service": bool(meta.get("runtime_service", False)),
        "source_authority": str(meta.get("source_authority", "")),
        "source_url": str(meta.get("source_url", "")),
        "public_url": str(meta.get("public_url", "")),
        "source_ref": str(meta.get("source_ref", "")),
        "source_sha": str(meta.get("source_sha", "")),
        "source_updated": str(meta.get("source_updated", "")),
    }
