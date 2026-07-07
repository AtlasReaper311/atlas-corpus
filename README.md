<div align="center">
  <img src="https://raw.githubusercontent.com/AtlasReaper311/AtlasReaper311/main/atlas-icon-dark-256.png" width="88" alt="Atlas Systems"/>
</div>

# atlas-corpus

```
┌─────────────────────────────────────────────┐
│  ATLAS SYSTEMS // atlas-corpus              │
│  semantic search over everything the        │
│  estate has ever written or decided         │
└─────────────────────────────────────────────┘
```

![Python](https://img.shields.io/badge/python-3.12-f5a623?style=flat-square&labelColor=0a0a0f)
![FastAPI](https://img.shields.io/badge/api-fastapi-4ade80?style=flat-square&labelColor=0a0a0f)
![Vector store](https://img.shields.io/badge/vectors-chromadb-aaa9a0?style=flat-square&labelColor=0a0a0f)
![Cost](https://img.shields.io/badge/cost-%C2%A30-aaa9a0?style=flat-square&labelColor=0a0a0f)

A queryable knowledge layer over everything Atlas Systems has produced: every README in the estate, the decisions log, the case studies and articles as published, and the brand and context documents. Ingested from GitHub, chunked, embedded locally, stored in Chroma, and searchable by meaning from the site and from Ramone. Pushes to any repo tell it to re-ingest, so the corpus tracks the estate instead of drifting behind it.

```
GitHub (READMEs · decisions.md · work/*.html · writing/*.html)
docs/ (brand doc · context doc)
   │  ingest: fetch ──▶ html-to-text ──▶ chunk 512/64 ──▶ embed ──▶ upsert
   ▼
nomic-embed-text ──▶ ChromaDB atlas_corpus (cosine)      [containers]
                          │
POST /search ──▶ embed ──▶ top-k + provenance     POST /refresh ◀── Actions on push
```

## Prerequisites

- Docker Engine with the compose plugin (or Docker Desktop)
- [Ollama](https://ollama.com) on the host with `nomic-embed-text` pulled
- A fine-grained GitHub PAT with public repo read (optional but strongly recommended: unauthenticated GitHub allows 60 requests/hour and a full ingest uses more)

## Setup

```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
# paste into CORPUS_SECRET= and GITHUB_TOKEN= in .env, then:
docker compose up --build -d
docker compose logs -f corpus
```

The stack refuses to start without `CORPUS_SECRET`, the same fail-closed rule as the rag stack's `ATLAS_SECRET`. First boot waits for Ollama and Chroma, then ingests in the background; watch the per-document log lines, then:

```bash
curl -sS http://localhost:8092/health
curl -sS http://localhost:8092/index | head -c 600
curl -sS -X POST http://localhost:8092/search \
  -H "Content-Type: application/json" \
  -d '{"query": "why do routes use zone_id instead of zone_name?"}'
curl -sS -X POST http://localhost:8092/ask \
  -H "Content-Type: application/json" \
  -d '{"query": "how do deploys get to Cloudflare?"}'
```

Drop the brand and context documents into `docs/` (gitignored, mounted read-only) and refresh; they ingest as `doc_type: doc`.

### Tunnel hostname

The widget calls the service directly, so it gets its own public hostname. Add to `C:\ProgramData\cloudflared\config.yml` above the catch-all:

```yaml
  - hostname: corpus.atlas-systems.uk
    service: http://localhost:8092
```

```powershell
cloudflared tunnel route dns <TUNNEL-NAME> corpus.atlas-systems.uk
Restart-Service cloudflared
```

If the tunnel runs on Windows and Docker in WSL2, port 8092 needs the portproxy rule; [`atlas-bootstrap`](https://github.com/AtlasReaper311/atlas-bootstrap) owns that rule and its on-boot refresh.

### Keeping it current on push

`github-trigger/.github/workflows/refresh-corpus.yml` is a reusable workflow. Any repo's caller gains freshness with one job:

```yaml
  refresh-corpus:
    uses: AtlasReaper311/atlas-corpus/.github/workflows/refresh-corpus.yml@main
    secrets:
      CORPUS_SECRET: ${{ secrets.CORPUS_SECRET }}
```

Set the secret once per repo (`gh secret set CORPUS_SECRET --repo ...`). A corpus that is offline fails soft: the step warns, the push does not fail, and the next trigger catches up.

### The widget

Paste the whole of [`site-snippet/corpus-search.html`](site-snippet/corpus-search.html) where corpus Q&A should live. Scoped under `.cs-w`, inherits the site's variables, calls `/ask`, renders the synthesized prose answer, and shows cited repo/file tags underneath. `/search` stays available for callers that need raw retrieved chunks.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/search` | none (rate-limited) | Semantic search: `{query, top_k?}` → hits with provenance |
| `GET/POST` | `/ask` | none (rate-limited) | Grounded Q&A: retrieve top-k chunks, synthesize with Ollama, return `{answer, sources}` |
| `GET` | `/index` | none | Every indexed document with chunk counts and last update |
| `POST` | `/refresh` | `x-corpus-secret` | Start a re-ingest; answers 202 immediately |
| `GET` | `/health` | none | Service, Chroma, Ollama status, corpus size |

## Adding a document source

Pinned single files are configuration: extend `EXTRA_FILES` with `repo:path:doc_type` entries. New HTML areas of the site are two env values (`*_PREFIX`). A genuinely new kind of source (another host, another format) is one function in `app/ingester.py` returning `(repo, path, doc_type, text)` tuples; chunking, embedding, upsert, and pruning are already source-agnostic.

## Design notes

**The public endpoint carries its own armour.** `/search` is called by browsers straight through the tunnel, so ramone-edge's protections move down a layer: a sliding per-IP hourly rate limit (Cloudflare's `CF-Connecting-IP` through the tunnel), a 500-character query cap, and a CORS allowlist. `/refresh` mutates and is secret-gated, fail-closed at startup.

**Re-ingest converges, never accretes.** Chunk ids are deterministic (`sha1(repo:path:index)`), so a refresh upserts in place and prunes indexes past a shrunken document's new length. The corpus is a projection of the sources, not a history of them.

**Refreshes are single-flight and non-blocking.** `/refresh` answers 202 and works behind a lock; a trigger during a running ingest is acknowledged and dropped, because ingest is idempotent and the next push refreshes again anyway. A failed pass keeps the previous corpus live.

**Word-window chunking, on purpose.** 512 words with 64 of overlap approximates the token spec without buying a tokenizer dependency; `nomic-embed-text`'s 8k window has an order of magnitude of headroom, and retrieval quality at this corpus size is bounded by the writing, not the splitter.

## How it fits into Atlas Systems

This is the estate's own writing made queryable. It shares the host Ollama and the `nomic-embed-text` model with [`ramone-memory`](https://github.com/AtlasReaper311/ramone-memory), runs the same pinned-Chroma compose shape as [`ollama-rag-kit`](https://github.com/AtlasReaper311/ollama-rag-kit), reuses [`ramone-edge`](https://github.com/AtlasReaper311/ramone-edge)'s tunnel exposure pattern, and stays current through the same reusable-workflow mechanism the whole pipeline deploys with. [`atlas-bootstrap`](https://github.com/AtlasReaper311/atlas-bootstrap) starts it on a rebuilt machine.

A knowledge base you have to remember to update is documentation; one that updates because the pipeline ran is infrastructure, and the difference is a webhook.

---

Part of [atlas-systems.uk](https://atlas-systems.uk)
