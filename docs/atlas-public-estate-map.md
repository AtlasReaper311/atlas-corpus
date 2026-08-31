---
title: Atlas Systems public estate map
type: public-estate-map
source_scope: public
lifecycle: production
authority: curated-public-projection
---

# Atlas Systems public estate map

Atlas Systems is a public-facing software and infrastructure estate built around
small repositories, published writing, public services, and local AI systems.
This document is a public projection: it describes only public-safe projects and
current relationships, not the private operator workspace.

## Public surfaces

- `atlas-systems.uk` is the public portfolio, writing, Work, Lab, Systems, and About site.
- `ramone.atlas-systems.uk` is the public browser Ramone interface.
- `corpus.atlas-systems.uk` is the public Atlas estate retrieval and answer service.
- `status.atlas-systems.uk` is the public status surface.
- Public GitHub repositories and READMEs provide source-level evidence.

## Main public layers

- `atlas-systems`: the public site and evidence presentation layer.
- `ramone-edge`: the public Cloudflare Worker gateway for browser Ramone.
- `ollama-rag-kit`: the public Ramone retrieval, prompt, streaming, and answer service.
- `atlas-corpus`: the public-safe search and answer source for estate facts.
- `atlas-infra`: public governance, classification, contracts, and ADR authority.
- `specular-core-public-profile`: the public-safe machine and local-inference profile.

## How the layers relate

The public browser path is:

`browser -> ramone-edge -> ollama-rag-kit -> atlas-corpus -> local generation`

The public corpus is not a mirror of every Atlas file. Inclusion requires an
explicit public classification or a curated public document. Unknown material is
excluded by default.

## Current truth rule

Current repository source, approved public classification, published site material,
and live probes answer different questions. A historical handoff can explain where
the estate came from, but it cannot override current source or live evidence.

## Explicit exclusions

This map does not include private repositories, personal documents, CV or
application material, university work, private memory, Home Assistant secrets,
`.env` files, tokens, private messages, or raw operator transcripts.
