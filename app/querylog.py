"""Query logging for atlas-corpus: SQLite at the source.

Why SQLite here and not KV at the edge (decisions.md :: conditional
write rule): logging belongs inside the hot path's own failure domain.
A per-query network write would add a remote dependency to every search
and burn edge write quota for data that is only ever read in hourly
aggregate. WAL keeps the single writer from blocking readers; one
connection per call is cheap at portfolio traffic and sidesteps
cross-thread connection sharing entirely (every call here runs via
asyncio.to_thread from main.py).

What is stored per query: timestamp, query text (capped), result count,
latency. What is never stored: IPs, user agents, headers, or any client
identity; this module is never handed those values, which makes the
card's privacy line structural rather than promissory.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections import Counter
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    query TEXT NOT NULL,
    result_count INTEGER NOT NULL,
    took_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_queries_ts ON queries (ts);
"""

_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-]{2,}")

# Small and boring on purpose: enough to keep "how does the" out of the
# top terms, not an NLP project.
_STOPWORDS = frozenset(
    "the a an and or of to in for on with from into onto over under "
    "what how why when where who which is are was were be been does do "
    "did can could should would will this that these those it its my "
    "your our their there here not no yes any all some but if then "
    "than as at by about you i we they he she them his her".split()
)


def _connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=5)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(_SCHEMA)
    return con


def log_query(path: str, query: str, result_count: int, took_ms: int) -> None:
    """Insert one query row; failures are swallowed by contract."""
    try:
        con = _connect(path)
        try:
            with con:
                con.execute(
                    "INSERT INTO queries (ts, query, result_count, took_ms) "
                    "VALUES (?, ?, ?, ?)",
                    (int(time.time()), query[:500], int(result_count), int(took_ms)),
                )
        finally:
            con.close()
    except (sqlite3.Error, OSError):
        # Logging must never break search; a dead log file surfaces soon
        # enough as flatlined counts in the hourly summary.
        pass


def stats(path: str) -> dict:
    """Aggregate counts for /stats and the hourly summary payload."""
    now = int(time.time())
    day_start = now - (now % 86400)
    try:
        con = _connect(path)
        try:
            total = con.execute("SELECT COUNT(*) FROM queries").fetchone()[0]
            last_hour = con.execute(
                "SELECT COUNT(*) FROM queries WHERE ts >= ?", (now - 3600,)
            ).fetchone()[0]
            today = con.execute(
                "SELECT COUNT(*) FROM queries WHERE ts >= ?", (day_start,)
            ).fetchone()[0]
            last_ts = con.execute("SELECT MAX(ts) FROM queries").fetchone()[0]
        finally:
            con.close()
    except (sqlite3.Error, OSError):
        return {
            "queries_last_hour": 0,
            "queries_today": 0,
            "queries_total": 0,
            "last_query_at": None,
        }
    return {
        "queries_last_hour": last_hour,
        "queries_today": today,
        "queries_total": total,
        "last_query_at": _iso(last_ts) if last_ts else None,
    }


def window_summary(path: str, since: int, until: int) -> dict:
    """Count plus top terms for one window, stopworded and capped at five."""
    try:
        con = _connect(path)
        try:
            rows = con.execute(
                "SELECT query FROM queries WHERE ts >= ? AND ts < ?",
                (since, until),
            ).fetchall()
        finally:
            con.close()
    except (sqlite3.Error, OSError):
        return {"count": 0, "top_terms": []}

    terms: Counter[str] = Counter()
    for (query,) in rows:
        for token in _TOKEN.findall(query.lower()):
            if token not in _STOPWORDS:
                terms[token] += 1

    return {
        "count": len(rows),
        "top_terms": [
            {"term": term, "count": count} for term, count in terms.most_common(5)
        ],
    }


def _iso(ts: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
