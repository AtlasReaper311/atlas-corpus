# Atlas Systems Public Context

Last updated: 2026-07-13

Atlas Systems is a live technical estate and portfolio surface owned by Atlas Reaper. It is designed to show working infrastructure rather than only describe it: public website, live status surfaces, retrieval services, automation, case studies, and local AI infrastructure.

Public domain: `https://atlas-systems.uk/`

GitHub owner: `AtlasReaper311`

Public audience: technical recruiters, senior engineers, collaborators, and anyone evaluating Atlas as an engineer.

## What Exists

- `atlas-systems.uk` is the main website. It hosts the Work index, Writing, Lab, About, and live technical demos.
- `status.atlas-systems.uk` is the public status surface with SLO-style component health and activity feed.
- `api.atlas-systems.uk/` is the public API registry and self-documenting entry point for Atlas Workers.
- `corpus.atlas-systems.uk` is the public retrieval service behind estate search and corpus-backed answers.
- `ramone.atlas-systems.uk` is the public browser Ramone entry point. It answers from public Atlas Systems material only.
- `specular-tunnel.atlas-systems.uk` exposes public-safe SPECULAR-CORE telemetry through an edge Worker for the Lab.

## Current Public Writing

The public case-study series currently includes:

- W-01 SONIN: autonomous generative audio/visual system in Max/MSP and Jitter.
- W-02 SlamPunk: dynamic game music and mix engine in Unreal Engine 5.
- W-03 Ramone: local AI system on SPECULAR-CORE.
- W-04 SPECULAR-CORE Overclocking: workstation tuning for audio, local inference, and infrastructure workloads.

Scheduled or planned public writing includes pipeline infrastructure, self-documenting estate work, and further system case studies.

## Estate Shape

Atlas Systems is organised around small, named services rather than one monolith. Common repo naming uses subsystem prefixes such as `atlas`, `ramone`, and `specular`.

Important public systems:

- `atlas-systems`: main website.
- `atlas-corpus`: estate RAG/search service.
- `ollama-rag-kit`: public Ramone upstream for browser chat.
- `ramone-edge`: Cloudflare Worker front for public Ramone.
- `specular-telemetry` and `specular-edge`: local machine telemetry plus public-safe edge proxy.
- `atlas-api-index`: public API registry.
- `atlas-api-public`: public metadata, status, manifest, and SLO-style API surface.
- `atlas-infra`: reusable CI/CD workflows and estate decisions.
- `atlas-notify`: notification router for Worker runtime events.
- `ramone-voice-trigger`: private voice-to-deploy Worker path.

## Public Boundaries

Public Atlas Systems knowledge includes public repos, published case studies, public website content, public API metadata, and public-safe explanations of the local machine and infrastructure.

Public Atlas Systems knowledge excludes:

- University notes, coursework, study notes, marks, or drafts.
- Books, reading notes, or imported reference-library material.
- CVs, cover letters, employment applications, salary, or interview material.
- Employer-specific material.
- Private Ramone memory.
- Secrets, tokens, credentials, `.env` files, Home Assistant tokens, and deploy keys.

If a public answer needs any excluded material, Ramone should refuse or say the corpus does not cover it.

## Current Local Context For Public Answers

The live public corpus check on 2026-07-13 reported 32 documents and 89 chunks before this promotion pass. The goal of this pass is to add richer public-safe context so Ramone can answer beyond READMEs and old brand notes.

Top-level `docs/*.md` files are ingested as public corpus documents. Nested folders are staging only.
