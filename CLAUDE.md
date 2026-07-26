# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Voicebox is a **local-first AI voice studio** — an open-source alternative to ElevenLabs (TTS) and WisprFlow (voice input) in a single desktop app. It clones voices, generates speech across 7 TTS engines in 23 languages, provides global push-to-talk dictation, and exposes an MCP server so AI agents can speak and transcribe.

- **Desktop app**: Tauri (Rust) shell around a React/TypeScript frontend
- **Backend**: Python FastAPI server (port 17493) with SQLite
- **Web deployment**: Same React frontend served by FastAPI in Docker
- **7 TTS engines**: Qwen3-TTS, Qwen CustomVoice, LuxTTS, Chatterbox Multilingual, Chatterbox Turbo, HumeAI TADA, Kokoro
- **Voice input**: Whisper-based STT with global hotkey dictation (macOS keyboard tap via Tauri)
- **Personality LLM**: Bundled Qwen3 (0.6B/1.7B/4B) for text refinement and in-character speech
- **MCP server**: Built-in FastMCP server at `/mcp` with `voicebox.speak`, `voicebox.transcribe`, `voicebox.list_captures`, `voicebox.list_profiles`

## Prerequisites

- **Bun** (>=1.0.0) — JS runtime/package manager
- **Python 3.11+** — backend
- **Rust** — Tauri desktop app
- **[just](https://github.com/casey/just)** — task runner (`brew install just` or `cargo install just`)

Run `just --list` to see all available commands.

## Common Commands

### Development

```bash
just setup        # create venv, install Python + JS deps (run once)
just dev          # start backend + Tauri desktop app (main dev command)
just dev-web      # backend + web app (no Tauri/Rust build)
just dev-backend  # backend only on port 8000
just kill         # stop all dev processes
```

### Testing

```bash
just test         # run all Python tests (pytest)
just test-e2e     # E2E: generate with every TTS model (pass --only kokoro for one engine)
```

To run a single test:

```bash
cd backend && python -m pytest tests/test_audio_preprocess.py -xvs
```

### Linting & Formatting

```bash
just check        # JS + Python lint + format check
just fix          # auto-fix JS + Python lint/format issues
just lint         # lint only (JS + Python)
just format       # format only (JS + Python)
```

- **JS/TS**: Biome (`biome lint .`, `biome format --write .`)
- **Python**: ruff (`ruff check`, `ruff format`)

### Type Checking

```bash
just typecheck    # tsc --noEmit for app/ + web/
```

### Building

```bash
just build        # build Python server binary + Tauri desktop app
just build-server # CPU server binary only (PyInstaller)
just build-web    # web frontend only
```

### Database

```bash
just db-init      # initialize SQLite database
just db-reset     # delete and reinit database
```

### API

```bash
just docs         # open Swagger docs at http://127.0.0.1:17493/docs
just api-client   # regenerate TypeScript API client (backend must be running)
```

## Architecture

### Directory Structure

```
voicebox/
├── backend/          # Python FastAPI server
│   ├── backends/     # TTS/STT/LLM engine implementations (protocol-based)
│   ├── routes/       # FastAPI route handlers (one file per resource)
│   ├── services/     # Business logic (generation, profiles, tts, transcribe, llm, etc.)
│   ├── mcp_server/   # FastMCP server (tools, context, resolve, events)
│   ├── mcp_shim/     # Stdio→HTTP bridge binary for MCP clients
│   ├── database/     # SQLAlchemy models, migrations, session management
│   ├── utils/        # Audio processing, chunking, effects, platform detection
│   └── tests/        # pytest test suite
├── app/              # Shared React/TypeScript frontend (SPA)
├── tauri/            # Tauri desktop app (Rust shell)
├── web/              # Web deployment entry point (Vite)
├── landing/          # Marketing website (astro)
└── scripts/          # Build & release shell scripts
```

### Backend Core

**`backend/app.py`** — FastAPI application factory (`create_app()`). Sets up:
- Colored logging, ROCm GPU detection (before torch import)
- CORS middleware (localhost origins + tauri://)
- `ClientIdMiddleware` (extracts `X-Voicebox-Client-Id` header for MCP)
- Lifespan: DB init, stale generation cleanup, model cache prep, background CUDA/ROCm binary checks
- MCP app mounted at `/mcp` (FastMCP Streamable HTTP transport)
- SPA catch-all serving `frontend/` when present (Docker/web mode)

**`backend/config.py`** — Data directory management. `VOICEBOX_MODELS_DIR` env var overrides HuggingFace cache. Data dir defaults to `./data/` with subdirectories for profiles, generations, captures, cache, models. `VOICEBOX_CLOUD_URL` / `VOICEBOX_CLOUD_API_URL` for cloud sync.

**`backend/database/`** — SQLAlchemy with SQLite. Key models:
- `VoiceProfile` — voice_type discriminates `cloned` (reference audio), `preset` (engine-specific like Kokoro voices), `designed` (text-described)
- `Generation` — TTS output with status, engine, seed, instruct, source tracking
- `Capture` — voice input with raw/refined transcripts
- `MCPClientBinding` — per-client voice configuration (client_id → profile, engine, personality)
- `CaptureSettings`, `GenerationSettings` — singleton preference rows (id=1)

### TTS Backend Architecture

The multi-engine system uses a **Protocol-based abstraction** (`TTSBackend`, `STTBackend`, `LLMBackend` in `backends/__init__.py`). Each engine is a class conforming to the protocol:

```
TTSBackend Protocol:
  load_model(model_size?) → None
  create_voice_prompt(audio_path, reference_text) → (voice_prompt_dict, was_cached)
  combine_voice_prompts(audio_paths, reference_texts) → (audio_array, combined_text)
  generate(text, voice_prompt, language, seed, instruct) → (audio_array, sample_rate)
  unload_model() → None
  is_loaded() → bool
```

**Engine registry** (`TTS_ENGINES` dict in `backends/__init__.py`):
| Key | Engine | Backend Class |
|-----|--------|---------------|
| `qwen` | Qwen3-TTS | `MLXTTSBackend` or `PyTorchTTSBackend` |
| `qwen_custom_voice` | Qwen CustomVoice | `QwenCustomVoiceBackend` |
| `luxtts` | LuxTTS | `LuxTTSBackend` |
| `chatterbox` | Chatterbox TTS | `ChatterboxTTSBackend` |
| `chatterbox_turbo` | Chatterbox Turbo | `ChatterboxTurboTTSBackend` |
| `tada` | HumeAI TADA | `HumeTadaBackend` |
| `kokoro` | Kokoro | `KokoroTTSBackend` |

**Factory function**: `get_tts_backend_for_engine(engine)` — double-checked locking, thread-safe lazy instantiation. MLX vs PyTorch selection happens at the `qwen` engine level based on `platform_detect.get_backend_type()`.

**ModelConfig** dataclass declares downloadable model variants with HF repo IDs, sizes, language support. Configs are backend-aware (MLX uses `mlx-community/` quants, PyTorch uses upstream repos).

### Generation Pipeline

1. **`routes/generations.py`** receives request → creates `Generation` row (status=`queued`)
2. **`services/task_queue.py`** enqueues the generation coroutine in a **serial `asyncio.Queue`** — prevents GPU contention
3. **`services/generation.py:run_generation()`** — unified orchestrator for generate/retry/regenerate:
   - Loads engine model if needed
   - Creates voice prompt from profile's reference samples
   - Calls `generate_chunked()` from `utils/chunked_tts.py`
   - Applies post-processing effects chain if configured
   - Saves audio, creates version records
   - Updates generation status (completed/failed)
4. **SSE streaming** — frontend polls `/generate/{id}/status` or listens to SSE events for real-time progress

### Chunked TTS (`utils/chunked_tts.py`)

Long text is split at sentence boundaries (respecting abbreviations, CJK punctuation, `[tags]`), each chunk is generated independently, then concatenated with crossfade. Configurable via `max_chunk_chars` (default 800) and `crossfade_ms` (default 50) in `GenerationSettings`.

### Post-Processing Effects (`utils/effects.py`)

Uses `pedalboard` for: pitch shift, reverb, delay, chorus, compression, low-pass/high-pass filters. Effects chains are validated before application. Presets stored in `EffectPreset` table.

### MCP Server (`mcp_server/`)

- **`server.py`** — builds FastMCP instance, composes lifespan with FastAPI
- **`tools.py`** — 4 tool implementations, thin wrappers over existing services
- **`context.py`** — `ClientIdMiddleware` extracts `X-Voicebox-Client-Id` into a `ContextVar`
- **`resolve.py`** — profile resolution precedence: explicit arg → per-client binding → global default
- **`events.py`** — SSE pub/sub for speak-start/speak-end events (powers the dictation pill overlay)

The `mcp_shim/` subpackage builds a standalone `voicebox-mcp` binary (PyInstaller) that bridges stdio MCP clients to the HTTP MCP endpoint.

### Voice Personalities (`services/personality.py`, `services/llm.py`)

Profiles can have a `personality` text field describing the character. Two actions:
- **Compose** — LLM generates a fresh in-character line
- **Speak in character** — routes input text through the personality LLM for rewriting before TTS

The same Qwen3 LLM backs dictation refinement (`services/refinement.py`). MLX on Apple Silicon, PyTorch elsewhere.

### GPU Support Matrix

Detection in `utils/platform_detect.py` and `backends/base.py:get_torch_device()`:
- **macOS (Apple Silicon)**: MLX (Metal) via `mlx-community` quants
- **Windows/Linux (NVIDIA)**: PyTorch CUDA
- **Linux (AMD)**: PyTorch ROCm — auto-configures `HSA_OVERRIDE_GFX_VERSION` for older GPUs
- **Windows (any GPU)**: DirectML
- **Intel Arc**: IPEX/XPU

### Frontend

- **`app/`** — React/TypeScript SPA with Vite, Tailwind CSS v4, Radix UI primitives, `@tanstack/react-query`
- **`tauri/`** — Tauri v2 desktop shell. Rust source at `tauri/src-tauri/`. The Tauri app spawns the Python backend as a sidecar binary in production; in dev, it connects to a manually-started server
- **`web/`** — Vite web deployment entry point (slim wrapper around `app/`)
- **`landing/`** — Astro marketing site

The backend serves the built frontend from `frontend/` in Docker/web mode (SPA catch-all).

### Production Build

The Python server is frozen into a standalone binary via PyInstaller (`backend/build_binary.py`). Two binaries: `voicebox-server` (main) and `voicebox-mcp` (stdio shim). Platform-specific PyInstaller hooks live in `backend/pyi_hooks/` and runtime hooks in `backend/pyi_rth_*.py`. The CUDA variant bundles CuPy/NVIDIA libs; the ROCm variant targets AMD GPUs.

## Docker

```bash
# CPU
docker compose up --build

# AMD ROCm
docker compose -f docker-compose.yml -f docker-compose.rocm.yml up --build
```

Backend serves on port 17493 (API + SPA). 3-stage Docker build: frontend (Bun/Vite) → Python deps (pip) → runtime.

## Key Environment Variables

- `VOICEBOX_MODELS_DIR` — override HuggingFace model download cache
- `VOICEBOX_CORS_ORIGINS` — comma-separated additional CORS origins
- `VOICEBOX_CLOUD_URL` / `VOICEBOX_CLOUD_API_URL` — cloud sync endpoints
- `HSA_OVERRIDE_GFX_VERSION` — ROCm GPU compatibility override
- `HF_HUB_OFFLINE=1` — force offline mode (no HF metadata calls)

## Adding a New TTS Engine

Implement the `TTSBackend` protocol in `backend/backends/`, register in `TTS_ENGINES` dict and the `get_tts_backend_for_engine()` factory, add `ModelConfig` entries in `_get_non_qwen_tts_configs()`, then wire the frontend. See `.agents/skills/add-tts-engine/SKILL.md` for the full AI-assisted integration guide.

## Design Decisions

- **Serial generation queue** — only one TTS inference at a time to prevent GPU VRAM contention
- **Chunked generation** — text split at sentence boundaries with crossfade; avoids model context limits
- **DB-relative paths** — audio files referenced by path relative to data dir via `config.to_storage_path()` / `resolve_storage_path()`; supports movable data directory
- **Singleton settings rows** — `CaptureSettings` and `GenerationSettings` use id=1 singleton pattern (not key-value store)
- **Protocol-based backends** — `typing.Protocol` with `@runtime_checkable` allows duck-typing without ABC inheritance
- **Double-checked locking** — backend factory uses threading lock for thread-safe lazy init
- **HF offline patches** — `utils/hf_offline_patch.py` monkey-patches transformers to avoid crashing on `HF_HUB_OFFLINE=1`
