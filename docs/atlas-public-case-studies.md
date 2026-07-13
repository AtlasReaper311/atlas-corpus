# Atlas Systems Public Case Study Context

Last updated: 2026-07-13

This file gives public-safe operational context behind the published Atlas Systems case studies. It is written for retrieval, so Ramone can answer "how does it work?" questions with more detail than a card summary.

## W-01 SONIN

SONIN is an autonomous generative audio/visual system built in Max/MSP and Jitter. It composes evolving music and visuals in real time by listening to its own output, analysing that output, and feeding the analysis back into generation.

Core architecture:

- Melodic engine: scale-constrained pitch generation, probability-weighted rhythm, register and density changes driven by feedback.
- Granular engine: `poly~` voice management, grain envelopes, and decoupled pitch/duration handling.
- Feedback network: RMS, brightness/zero-crossing or spectral features, smoothing, clipping, and non-linear mapping.
- Visual engine: GPU-side Jitter pipeline so visual processing does not block the audio thread.
- Interface: macro controls, preset interpolation, and constrained randomisation.

Main engineering problems:

- Clock drift from continuously changing a `metro` interval.
- Grain voice stealing creating audible clicks.
- Positive feedback collapsing to silence or exploding to maximum density.

Final solution:

- Sample-and-hold quantisation for control paths.
- Forced short fade before voice reallocation.
- Non-linear scaling plus dampening in the feedback loop.
- GPU separation for visual computation.

The important public point: SONIN is a closed-loop system, not a sequencer. Its behaviour emerges from feedback, constraints, and controlled randomness.

## W-02 SlamPunk

SlamPunk is a 15-stem dynamic music and mix system for a competitive future-sport game. It was built in Unreal Engine 5 using MetaSounds, Blueprints, submixes, and music produced in FL Studio.

Core architecture:

- 15 stems per arena track: five instrument groups across three intensity levels.
- 140 BPM lock across the soundtrack to preserve loop boundaries and sync.
- MetaSound graph with Wave Players per stem and a single authoritative sync pulse.
- Blueprint intensity logic driven from match state.
- Submix hierarchy for Music, SFX, and Environment.
- Sidechain ducking and EQ carve-outs so gameplay cues survive peak music intensity.

Main engineering problems:

- Static loops caused fatigue.
- Multi-stem playback drifted over time.
- Hardcoded music per level would not scale.
- Dense music masked SFX cues at high intensity.

Final solution:

- FL Studio frequency planning before export.
- Strict stem naming and export order.
- MetaSound stem interpolation.
- Central Level Music Matrix in Blueprint.
- Submix hierarchy with sidechain ducking.

The important public point: SlamPunk treats music as a gameplay-responsive system, not background decoration.

## W-03 Ramone

Ramone is the Atlas Systems local AI layer. It runs on SPECULAR-CORE using WSL2, native Linux Docker Engine, Ollama, ChromaDB, Open WebUI, and retrieval services.

Core architecture:

- Windows 11 host with WSL2 Ubuntu as the Linux execution layer.
- Native Linux Docker Engine inside WSL2; Docker Desktop is not used.
- Ollama runs locally and serves the model set.
- Open WebUI is the private local chat/workbot interface.
- `atlas-corpus` provides public estate retrieval.
- `ollama-rag-kit` is the public Ramone upstream.
- `ramone-memory` is private long-term memory.

Main engineering problems:

- Open WebUI initially looked for Windows-side Ollama via `host.docker.internal`, but the intended runtime was Linux-native Ollama.
- Fresh Ubuntu dependencies blocked the Ollama install until fixed.
- DrvFs/NTFS permissions and path case sensitivity caused model discovery problems.
- The installer-created `ollama` system account could not traverse the mounted Windows model path.

Final solution:

- Run Ollama natively inside WSL2 under the correct user context.
- Keep model paths case-correct.
- Avoid Unix permission operations on `/mnt/l`.
- Use Docker/WSL networking deliberately.
- Separate public browser session memory from private long-term memory.

The important public point: Ramone is a local-first AI estate, not a cloud chatbot wrapper.

## W-04 SPECULAR-CORE Overclocking

SPECULAR-CORE is the workstation that runs the Atlas local stack. The overclocking/tuning case study documents the work needed to make it stable for mixed AI, audio, Docker, and live-service workloads.

Core architecture:

- Ryzen 9 9950X3D with dual-CCD scheduling considerations.
- MSI Gaming Trio RTX 5070 for local model acceleration and visual workloads.
- 64 GB DDR5-6000 memory.
- High-speed NVMe storage for system, model, and estate workloads.
- AIO and fan curves tuned around audio use, not only temperature.
- Process Lasso rules for CCD-aware scheduling.

Main engineering problems:

- Stock settings left performance and scheduling stability on the table.
- Vendor curve tooling produced unreliable output.
- Windows scheduler needed help with latency-sensitive workloads on a dual-CCD CPU.
- Cooling profiles had to respect audio noise constraints.

Final solution:

- Manual memory/fabric tuning.
- Hand-built GPU voltage/frequency curve.
- AIO and case fan curves tuned against real use.
- Process Lasso affinity rules.
- Overnight validation before treating the profile as production-ready.

The important public point: the machine tuning supports the software architecture. Local AI, retrieval, voice, audio, and public demos all depend on predictable workstation behaviour.

## What To Add Next

The public corpus will get stronger if future case-study promotions include:

- Full published case-study text.
- System diagrams in text form.
- Design decisions and tradeoffs.
- Failure modes and final fixes.
- Current limits and what changed after publication.

Do not add private drafts, coursework, employer material, or personal notes.
