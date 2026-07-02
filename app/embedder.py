"""Ollama embedding for corpus chunks and queries.

/api/embed is the batched endpoint; ingestion sends chunks in batches
sized by config so one oversized request cannot stall Ollama, and a
query is just a batch of one.
"""

import logging

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


async def embed_batch(
    client: httpx.AsyncClient, settings: Settings, texts: list[str]
) -> list[list[float]]:
    """Embed texts in config-sized batches, preserving order."""
    embeddings: list[list[float]] = []
    for start in range(0, len(texts), settings.embed_batch_size):
        batch = texts[start : start + settings.embed_batch_size]
        response = await client.post(
            f"{settings.ollama_host}/api/embed",
            json={"model": settings.embed_model, "input": batch},
            timeout=settings.embed_timeout_seconds,
        )
        response.raise_for_status()
        got = response.json().get("embeddings", [])
        if len(got) != len(batch):
            raise RuntimeError(
                f"Ollama returned {len(got)} embeddings for {len(batch)} inputs; "
                f"is {settings.embed_model} pulled? (ollama pull {settings.embed_model})"
            )
        embeddings.extend(got)
    return embeddings


async def embed_query(
    client: httpx.AsyncClient, settings: Settings, text: str
) -> list[float]:
    """Embed one query string."""
    return (await embed_batch(client, settings, [text]))[0]
