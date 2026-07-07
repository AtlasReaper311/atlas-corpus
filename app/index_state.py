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
        entry = index.setdefault(
            key,
            {
                "source_repo": str(meta.get("source_repo", "")),
                "file_path": str(meta.get("file_path", "")),
                "doc_type": str(meta.get("doc_type", "")),
                "chunks": 0,
                "last_updated": str(meta.get("last_updated", "")),
            },
        )
        entry["chunks"] += 1
        if str(meta.get("last_updated", "")) > entry["last_updated"]:
            entry["last_updated"] = str(meta.get("last_updated", ""))
    return index
