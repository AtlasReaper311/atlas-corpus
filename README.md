<div align="center">
  <img src="https://raw.githubusercontent.com/AtlasReaper311/AtlasReaper311/main/atlas-icon-dark-256.png" width="88" alt="Atlas Systems"/>
</div>

# atlas-corpus

```
┌─────────────────────────────────────────────┐
│  ATLAS SYSTEMS // atlas-corpus              │
│  semantic search over the public estate     │
└─────────────────────────────────────────────┘
```

![Python](https://img.shields.io/badge/python-3.12-f5a623?style=flat-square&labelColor=0a0a0f)
![FastAPI](https://img.shields.io/badge/api-fastapi-4ade80?style=flat-square&labelColor=0a0a0f)
![Vector store](https://img.shields.io/badge/vectors-chromadb-aaa9a0?style=flat-square&labelColor=0a0a0f)
![Cost](https://img.shields.io/badge/cost-%C2%A30-aaa9a0?style=flat-square&labelColor=0a0a0f)

A queryable knowledge layer over the public Atlas Systems estate. Public repository READMEs, approved architecture documents, published case studies, and published articles are fetched from GitHub, chunked, embedded locally, stored in Chroma, and searched by meaning without turning owner-local or private repository context into a public source.

## Architecture

```text
public GitHub repositories
approved public ADRs and decisions
published work/*.html and writing/*.html
        │
        │ ingest
        ▼
HTML/text normalisation
        │
        ▼
type-aware chunking
        │
        ▼
nomic-embed-text
        │
        ▼
ChromaDB atlas_corpus
        │
        ├── POST /search
        └── GET/POST /ask
```

The source boundary is deliberate. The corpus uses GitHub's public repository listing for account-wide README discovery, explicitly configured public files for additional documents, and published site HTML. Local host context directories are not mounted into the corpus container and private repositories are not ingestion sources.

A refresh also removes chunks whose source document no longer belongs to the approved public source set. Tightening the public boundary therefore converges the existing vector store instead of leaving stale private or retired source material behind.

## Prerequisites

- Docker Engine with the Compose plugin, or Docker Desktop.
- Ollama on the host with `nomic-embed-text` available.
- A GitHub token with public repository read access is recommended for API rate limits.

## Setup

```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
docker compose up --build -d
docker compose logs -f corpus
```

Store the generated value in `CORPUS_SECRET` through the approved local environment path. The service refuses to start without it because `/refresh` mutates the index.

Ollama stays on the host and owns the GPU. The container reaches it through `host.docker.internal`; the Compose file maps the host gateway for native Linux as well as Docker Desktop.

## Public source policy

A document enters the corpus only through one of these paths:

1. README content from a non-fork, non-archived public repository returned by GitHub's public user repository API.
2. A pinned file explicitly listed in `EXTRA_FILES` from a public repository.
3. Published HTML under the configured `work/` or `writing/` prefixes in the public site repository.
4. Approved public ADRs gathered from the public infrastructure repository.

The corpus does not mount owner-local context documents. Repository authentication must not widen the source set: a token may increase API rate limits, but private repository visibility is not treated as permission to ingest private content.

Removed documents are pruned by `doc_key` on refresh. Existing chunks that are not present in the current approved source index are deleted from Chroma.

## Tunnel hostname

The public widget calls the corpus service directly. The Cloudflare Tunnel ingress is expected to route the public corpus hostname to local port `8092`.

The public endpoint carries its own browser-facing controls:

- CORS allowlist.
- Per-IP query rate limit.
- 500-character query cap.
- Secret-gated `/refresh` mutation.

The tunnel does not turn every local endpoint into a public contract. Only the documented read and refresh surfaces below are intended.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/search` | none, rate-limited | Semantic search with bounded `top_k` |
| `GET/POST` | `/ask` | none, rate-limited | Grounded answer with cited public sources |
| `GET` | `/index` | none | Current public source documents and chunk counts |
| `POST` | `/refresh` | `x-corpus-secret` | Start a single-flight public-source re-ingest |
| `GET` | `/health` | none | Service, Chroma, Ollama, and corpus health |
| `GET` | `/stats` | none | Aggregate query statistics without IP logging |

## Keeping it current

Push-triggered refresh is the primary freshness mechanism. A failed refresh keeps the previous collection live; a concurrent refresh request is acknowledged and dropped because ingestion is idempotent and the next trigger converges the same source set.

Chunk IDs are deterministic from repository, path, and chunk index. Unchanged chunks overwrite themselves; shortened documents prune excess chunks; documents removed from the public source set are removed entirely.

## Search behavior

Search combines the stored embeddings with the corpus's retrieval layer and returns provenance for each result. Query logging stores query text, result count, and latency locally; IP addresses are not logged.

The public question boundary also rejects categories that are outside the public estate, including credentials, private memory, employer material, and private application or academic material. The stronger control is still source selection: content outside the approved public source set should never reach Chroma in the first place.

## Development

```bash
python -m compileall app
python -m pytest
```

Use the repository's current CI workflow as the authority for the complete validation set before merging changes.

## Design notes

**Public source selection is the trust boundary.** A search service cannot safely depend on prompt-level refusals to protect material that was indexed by mistake. Private content is excluded before chunking and embedding.

**Refresh converges.** Deterministic chunk identities plus removed-source pruning mean the vector store represents the current approved source set rather than an append-only history of everything it has ever seen.

**Ollama remains local.** Embedding and generation run on owner-controlled hardware. The public service exposes bounded search behavior, not the underlying model runtime.

**Mutation fails closed.** `/refresh` requires a secret and the service refuses to boot without that configuration. Public read access never implies public write authority.

## How it fits into Atlas Systems

`atlas-corpus` supplies public semantic search to the Atlas Systems site and API while using the same local Ollama infrastructure as the wider AI stack. Its inputs follow the public/private estate boundary defined by `atlas-infra`, so the search surface can describe the public system without becoming a side channel into owner-operated repositories.

The transferable pattern is to make data publication explicit at ingestion time; filtering after retrieval is too late once private material has entered the index.

---

Part of [atlas-systems.uk](https://atlas-systems.uk)
