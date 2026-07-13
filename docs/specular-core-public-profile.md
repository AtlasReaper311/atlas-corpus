# SPECULAR-CORE Public Machine Profile

Last updated: 2026-07-13

SPECULAR-CORE is the primary workstation and active local production node behind Atlas Systems. It runs the local AI stack, public-safe telemetry, RAG services, Open WebUI, Home Assistant voice components, Docker services, and audio/game-development workloads.

## Hardware

| Component | Public spec |
|---|---|
| Case | Lian Li O11 Vision, Chrome |
| CPU | AMD Ryzen 9 9950X3D, 16 cores / 32 threads |
| Cooler | Ryujin III 360 Extreme ARGB Performance AIO, black, OLED, 360 mm |
| Fans | 6 x Lian Li UNI SL120 INF ARGB 120 mm fans with controller |
| Motherboard | Gigabyte X870 AORUS ELITE WIFI7 ATX for AMD AM5 |
| RAM | G.Skill Trident Z5 Neo EXPO RGB 64 GB, 2x32 GB, DDR5-6000, CL30 |
| GPU | MSI Gaming Trio RTX 5070 |
| PSU | Seasonic Focus GX-850 Gold |
| Storage | WD Black SN850X 2 TB NVMe and Crucial T705 2 TB NVMe PCIe Gen5 M.2 SSD |

Live local checks on 2026-07-13 reported Windows 11 Pro, a Ryzen 9 9950X3D, 64 GB class RAM, and an NVIDIA RTX 5070 with roughly 12 GB VRAM.

## Why The Tuning Matters

The W-04 SPECULAR-CORE Overclocking case study is not just a gaming/performance story. The tuning makes the Atlas local stack practical:

- EXPO memory tuning and fabric synchronisation reduce avoidable memory latency.
- A hand-built GPU voltage/frequency curve improves stability under mixed local inference and visual workloads.
- AIO and fan curves are tuned around real audio work, not just benchmark temperatures.
- Process Lasso CCD affinity helps the dual-CCD 9950X3D place latency-sensitive audio and inference work on the better-suited CCD.
- Docker, RAG, voice, browser, audio, and local model workloads can coexist more predictably.

That tuning is why SPECULAR-CORE works as a production node rather than only a fast desktop.

## Public Services On The Machine

Public or public-facing services currently associated with SPECULAR-CORE include:

- `atlas-corpus`: public RAG/search service behind `corpus.atlas-systems.uk`.
- `ollama-rag-kit`: public Ramone upstream behind `ramone.atlas-systems.uk`.
- `specular-telemetry`: public-safe local machine telemetry, exposed through `specular-edge`.
- Ollama: local model runtime. The raw tunnel is Cloudflare Access-gated, not open public infrastructure.

Local-only services include Open WebUI, Home Assistant, Portainer, Uptime Kuma, Kokoro TTS, Faster Whisper, OpenWakeWord, and ComfyUI when launched.

## Performance Boundaries

The RTX 5070's 12 GB VRAM class ceiling shapes model choice.

Fast/public-friendly models:

- `mistral:7b`
- `llama3.1:8b`
- `llama3.2:3b`
- `nomic-embed-text`

Pressure models:

- `ramone:latest`
- `qwen3:14b`
- `deepseek-coder-v2:16b`
- `qwen2.5:32b`

Do not assume multiple large models can run comfortably alongside ComfyUI or the voice pipeline. Browser-facing and voice-facing workloads should prefer low-latency models.

## Public Boundary

It is public-safe to say SPECULAR-CORE runs Atlas Systems' local AI, RAG, voice, telemetry, and development stack.

It is not public-safe to expose secrets, private memory, private source files, private notes, employer material, or personal documents from the machine.
