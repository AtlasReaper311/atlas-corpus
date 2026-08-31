---
title: Atlas Systems public history and transitions
type: public-history
source_scope: public
lifecycle: archive
authority: curated-public-projection
---

# Atlas Systems public history and transitions

This document records durable public transitions. Historical statements explain
where a system came from; they are not current operational instructions.

## Public retrieval transition

### What changed from the old Ramone setup?

The public path moved toward a separated browser gateway, RAG service, and
public-safe corpus: `ramone-edge` -> `ollama-rag-kit` -> `atlas-corpus`. Older
arrangements mixed experimental retrieval or older model labels into handoffs.
Those notes explain the transition, but the current path and current model are
defined by present public source and runtime evidence.

The public Ramone path was consolidated around `ramone-edge`, `ollama-rag-kit`,
and `atlas-corpus`. Earlier notes and handoffs may mention other model names,
older retrieval paths, or experimental arrangements. Those references describe
prior states and must not be used as current truth.

## Model transition rule

Older handoffs can contain stale model labels. The current model is determined by
the current public-safe runtime configuration and current curated profile. As of
the current projection, public answer generation uses `qwen3.5-mtp` through the
shared local llama.cpp endpoint. Historical labels such as `qwen3:14b` are not
current evidence.

## Why the history exists

Keeping a short, public-safe history lets Ramone answer “where did this come from?”
without exposing raw handoffs, private prompts, personal context, secrets, or
operator conversation. It also prevents old implementation details from being
mistaken for the present architecture.

## Authority order

For a current answer, prefer current approved source and published public pages,
then current deployment evidence, then a live probe when the question is about
health or availability. Use this history only for clearly historical questions.
