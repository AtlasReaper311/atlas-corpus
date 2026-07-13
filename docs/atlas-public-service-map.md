# Atlas Systems Public Service Map

Last updated: 2026-07-13

This file gives public-safe service context for Atlas Systems.

## Website And Public Surfaces

| Surface | Role |
|---|---|
| `atlas-systems.uk` | Main website, writing, Work index, Lab, and portfolio surface. |
| `status.atlas-systems.uk` | Public status and activity surface. |
| `api.atlas-systems.uk/` | Public API registry and self-documenting entry point. |
| `api.atlas-systems.uk/sonify` | Public sonification Worker for Lab experiments. |
| `corpus.atlas-systems.uk` | Public estate retrieval and answer service. |
| `ramone.atlas-systems.uk` | Public browser Ramone. |
| `specular-tunnel.atlas-systems.uk` | Public-safe SPECULAR-CORE telemetry through an edge Worker. |

## Important Repos

| Repo | Public role |
|---|---|
| `atlas-systems` | Main static website. |
| `atlas-corpus` | Public retrieval service using FastAPI, ChromaDB, embeddings, and Ollama. |
| `ollama-rag-kit` | Public Ramone upstream for browser chat. |
| `ramone-edge` | Cloudflare Worker front for public Ramone. |
| `ramone-memory` | Private/local long-term memory service; not public browser memory. |
| `ramone-voice-trigger` | Private voice-to-deploy path. |
| `specular-telemetry` | Local telemetry service for SPECULAR-CORE. |
| `specular-edge` | Edge proxy for public-safe telemetry. |
| `atlas-api-index` | Public registry of API/Worker surfaces. |
| `atlas-api-public` | Public metadata and status API. |
| `atlas-infra` | Reusable CI/CD workflows and decision records. |
| `atlas-notify` | Worker runtime notification router. |
| `atlas-owui-tools` | Open WebUI custom tools; integrated locally, valve tuning still pending. |

## Current Local Ports Worth Knowing

These are public-safe operational facts, not public invitations to connect:

| Port | Service |
|---|---|
| 3000 | Local Open WebUI. |
| 8000 | `ollama-rag-kit` public Ramone upstream. |
| 8091 | `ramone-memory` private/local long-term memory. |
| 8092 | `atlas-corpus` public retrieval service. |
| 8123 | Home Assistant local voice pipeline. |
| 8188 | ComfyUI when launched; on-demand only. |
| 9000 | `specular-telemetry`. |
| 9001 | Portainer local Docker UI. |
| 10200 / 8880 | Kokoro TTS. |
| 10300 | Faster Whisper via Wyoming protocol. |
| 10400 | OpenWakeWord via Wyoming protocol. |
| 11434 | Ollama raw API; Access-gated if exposed through Cloudflare. |

## Tooling State

`atlas-owui-tools` is integrated and available in Open WebUI. The remaining work is valve tuning: base URLs, allowlists, dry-run defaults, and container-level verification.

Mutating tools should stay dry-run/default-safe until valves are deliberately tuned.

## Current Fixed State

The latest Ramone voice and memory regression is fixed as of the 2026-07-13 audit. The failure mode remains documented because it can recur after Home Assistant, Docker, WSL, Ollama, or secret changes.

Public Ramone retrieval unification is complete: public browser Ramone uses `ollama-rag-kit` and `atlas-corpus`, not private long-term memory.
