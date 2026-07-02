# Why this exists

A static knowledge base answers the question you thought to organise for. Folders, filenames, a search box that matches strings: all of it assumes the future reader knows the past writer's vocabulary. Six months in, the estate's answers are scattered across a dozen READMEs, a decisions log, published case studies, and two identity documents, and the question that actually arrives is phrased like a question: "why did CI keep failing on the wildcard route?" String search finds that answer only if you already remember it involved `zone_name`. Semantic search finds it because the decisions log and the question mean the same thing.

The deeper shift is that a corpus with an embedding in front of it is a capability, not a document set. `POST /search` is callable by a site widget, by Ramone mid-conversation, by a future agent deciding whether a problem has been solved before. Each consumer costs nothing extra, because the work, fetching, cleaning, chunking, embedding, was done once at the layer they all share. A static knowledge base has readers; a queryable corpus has clients.

Freshness is the part most knowledge systems quietly fail. Documentation drifts because updating the index is a human chore, and human chores lose to deadlines every time. Here the chore is a webhook: every push that changes the estate tells the corpus to re-ingest, the ingest is idempotent and single-flight, and a corpus that happens to be offline just catches up on the next trigger. The index stays honest for the same reason the deploys stay green, because the pipeline does it, not because anyone remembered.

There is also a quieter payoff: the corpus is an audit of the writing itself. Ingesting your own estate exposes which repos explain themselves and which ones assume a reader who was in the room. A README that embeds badly, that retrieval never surfaces for the questions it should answer, is a README that needs rewriting, and now there is an instrument that says so.

The transferable principle: knowledge earns the name infrastructure when it is fetchable by meaning, current by mechanism, and consumable by more than one client. Anything else is a folder.
