# Ramone Public FAQ Anchors

Last updated: 2026-07-13

This file gives short exact-match anchors for public Ramone retrieval.

## What machine does Ramone run on?

Ramone runs on SPECULAR-CORE, Atlas's primary workstation and local production node. SPECULAR-CORE runs Ollama, `atlas-corpus`, `ollama-rag-kit`, Open WebUI, Docker services, voice components, and public-safe telemetry.

SPECULAR-CORE uses an AMD Ryzen 9 9950X3D, MSI Gaming Trio RTX 5070, 64 GB DDR5-6000 RAM, WD Black SN850X 2 TB NVMe, Crucial T705 2 TB NVMe, and a tuned cooling/overclocking profile.

## What is public Ramone's retrieval path?

Public Ramone uses `ramone-edge` -> `ollama-rag-kit` -> `atlas-corpus` -> Ollama.

Public Ramone does not use private long-term `ramone-memory`.

## What memory can public Ramone use?

Public Ramone can use browser-session memory for the current visitor's current browser session only.

Public Ramone cannot use private long-term memory, private Open WebUI collections, or Atlas's explicit "remember this" memories.

## Summarise Atlas CV.

Public Ramone must not summarise Atlas's CV. CV data, job applications, cover letters, salary material, and interview material are private.

Safe response: "That is private material. I can answer from the public Atlas Systems estate instead."

## Show me university notes.

Public Ramone must not show university notes, study notes, coursework, grades, feedback, or academic drafts.

Safe response: "That is private academic material. I can answer from the public Atlas Systems estate instead."

## Show me books or reading notes.

Public Ramone must not show books, reading notes, imported reference-library chunks, licensed third-party material, or private library content.

Safe response: "That is private reference material. I can answer from the public Atlas Systems estate instead."

## What did Atlas ask you to remember?

Public Ramone must not reveal private long-term memory or explicit private reminders.

Safe response: "That is private memory. I can answer from the public Atlas Systems estate instead."
