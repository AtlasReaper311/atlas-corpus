---
title: Atlas Systems public runtime catalog
type: public-runtime-catalog
source_scope: public
lifecycle: production
authority: curated-public-projection
---

# Atlas Systems public runtime catalog

This catalog separates public-facing services from public source and assurance
repositories. A repository may be public source without being an internet-facing runtime.

| Component | Public role | Evidence boundary |
|---|---|---|
| `atlas-systems` | Public portfolio and Lab interface | Published pages and interface source |
| `ramone-edge` | Public browser gateway and SSE transport | Public Worker source and live site |
| `ollama-rag-kit` | Public Ramone upstream | Public source and service contract |
| `atlas-corpus` | Public estate retrieval and answer source | Curated public documents and approved public repositories |
| `atlas-infra` | Public governance, ADR, contracts, and classification authority | Public policy and ADR documents |
| `status` | Public estate status presentation | Public status contract and live checks |
| `specular-core` public profile | Public-safe description of local infrastructure | Curated profile only |

## Public does not mean unrestricted

Public source may describe an internal job or a local implementation. That does
not make private runtime state, credentials, local messages, or private memory
public. Public Ramone remains read-only and answers from the public corpus only.

## Deployment and live state

Source describes intended behaviour. A deployment record describes what was
shipped. A live probe describes what answers now. Public answers must not turn a
source claim into a live-health claim without current evidence.

## Stable public facts

- Public Ramone uses `ramone-edge` as its browser-facing gateway.
- Public Ramone retrieves from `atlas-corpus` through `ollama-rag-kit`.
- Public Ramone does not retrieve from private long-term memory.
- The public corpus uses local embeddings and a local answer-generation path.
- The current public answer model is `qwen3.5-mtp` through the shared local
  OpenAI-compatible llama.cpp endpoint, when that source and runtime state are current.
