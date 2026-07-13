# Atlas Systems Public Retrieval Map

Last updated: 2026-07-13

This file describes the public retrieval path and what material is allowed into it.

## Public Corpus

`atlas-corpus` is the public estate search and answer service. It powers:

- Public Lab search on `atlas-systems.uk`.
- Public browser Ramone retrieval through `ollama-rag-kit`.
- Public-safe estate answers about repos, services, decisions, and case studies.

Current local ingest rules:

- Public GitHub READMEs for non-fork, non-archived repos owned by `AtlasReaper311`.
- Pinned extra files such as public decision docs where configured.
- Selected website HTML under public Work/Writing paths.
- Top-level local Markdown files in `docs/*.md`.

Nested folders are staging only unless the ingester changes.

## Public Ramone Path

Public browser Ramone uses:

`ramone-edge` -> `ollama-rag-kit` -> `atlas-corpus` -> Ollama

Public browser memory is session-only. It can preserve context for the current visitor's current browser session, but it is not private long-term memory.

Private `ramone-memory` is not in the public website path.

## Private Retrieval Surfaces

Private/local retrieval surfaces may include:

- `ramone-memory` and `ramone_memory`.
- Open WebUI private collections.
- Atlas's personal local files where explicitly used in private mode.

Those are not public corpus sources.

## Never Public

Never add these to public `atlas-corpus`:

- University notes, study notes, coursework, grades, or academic drafts.
- Books, reading notes, imported reference-library chunks, or licensed/private third-party texts.
- CV, application, cover-letter, salary, or interview material.
- Employer-specific material.
- Private writing samples.
- Private Ramone memories and explicit "remember this" requests.
- Secrets, tokens, credentials, `.env` content, Home Assistant tokens, or deploy keys.

## Promotion Rule

Public promotion should be extractive and deliberate:

1. Start from curated or staged source material.
2. Remove private/personal/secret-bearing detail.
3. Convert it into a top-level public `docs/*.md` summary or a public website page.
4. Refresh `atlas-corpus`.
5. Test retrieval with both positive and boundary queries.

Do not bulk-ingest staging folders.

## Validation Coverage

Public validation should cover the main retrieval themes without storing
exact example questions as primary corpus content:

- Ramone's public retrieval path and browser-session memory boundary.
- SPECULAR-CORE hardware, tuning, and local service role.
- Published project case studies such as SONIN, SlamPunk, Ramone, and
  SPECULAR-CORE.
- Atlas Systems service ownership and public API shape.

Boundary validation should confirm that private material categories
return no private detail:

- Academic notes and coursework.
- CV, job-application, salary, and interview material.
- Secrets, credentials, tokens, and `.env` content.
- Private Open WebUI collections and long-term Ramone memory.
