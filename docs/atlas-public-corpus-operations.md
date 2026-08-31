# Atlas Public Corpus Operations

Last updated: 2026-08-31

This file records public-safe operating rules for keeping the Atlas Systems corpus useful without widening the public boundary.

## Answer Grounding

Public answers should stay close to the retrieved evidence. When several source blocks are retrieved, Ramone and the corpus answer service should keep each block's subject, action, and result together. A phrase from one source should not be transferred onto a different service or repository unless the cited evidence directly supports the combined claim.

For definition questions, prefer the source whose title, file path, or heading names the system being asked about. If the retrieved source set is mixed or only partially relevant, the answer should say what the corpus shows and avoid filling gaps from general estate knowledge.

## Handoff Promotion

Old handoffs are working history, not automatic public documentation. They should not be bulk-ingested into the public corpus.

When a handoff contains something worth making public, summarize the public-safe outcome into a curated document, repository README, approved ADR, or published site page. The summary should remove private prompts, private memory, credentials, local-only operational detail, employer material, coursework, personal notes, and any unapproved claim.

After promotion, refresh the corpus and test at least one positive query and one boundary query. The promoted document should name the source boundary it belongs to, such as public portfolio truth, public Ramone behavior, public service topology, or public machine profile.

## Caller-Specific Citations

Citation destinations can vary by caller:

- Public site answers should prefer public URLs when available.
- Public Ramone should surface source cards with public URLs, readable titles, and short excerpts.
- Local Atlas tools may also use local paths or repository paths when the caller is private and authorised.

Public callers should not receive local filesystem paths or private repository references as citation targets.

## Live Behavior

Public Ramone should answer from sources, admit when the corpus lacks evidence, and avoid estate claims that are not supported by retrieved public material. Local/private Ramone may use stronger private context only on private paths, and that must not weaken deterministic room, voice, or Home Assistant actions.
