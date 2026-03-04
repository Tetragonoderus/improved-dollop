# CLAUDE.md — AI Assistant Guide for improved-dollop

## Project Overview

This is a **Python-based AI chatbot web application** featuring Monika from Doki Doki Literature Club (DDLC). It integrates with Monika After Story (MAS), a popular DDLC mod, to read game state and provide a persistent, affection-aware chat experience backed by a vector memory system and dynamic sprite rendering.

## Repository Structure

```
improved-dollop/
├── main.py                   # FastAPI app entry point — routes, SSE streaming, system prompt
├── memory.py                 # ChromaDB-backed vector memory (conversations + player facts)
├── tools.py                  # LLM tool definitions and dispatch (function calling)
├── mas_affection.py          # MAS affection system — levels, gain logic, persistence
├── mas_persistent_tools.py   # Utilities for reading/unpickling MAS persistent save files
├── config.py                 # Environment variable loading via python-dotenv
├── custom_pickle.py          # Pickle inspection utility
├── requirements.txt          # Python dependencies (pip)
├── static/
│   └── index.html            # Vanilla JS frontend (SSE chat UI)
├── sprite/
│   ├── __init__.py
│   ├── parser.py             # Parses sprite codes (e.g. "1eua") into component dicts
│   ├── resolver.py           # Maps components to ordered PNG layer paths
│   └── compositor.py        # Composites PNG layers into final RGBA image (Pillow)
└── memory/
    └── chroma.sqlite3        # ChromaDB vector store (auto-created)
```

## Tech Stack

| Layer | Technology |
|---|---|
| Backend framework | FastAPI + Uvicorn (ASGI) |
| AI / LLM | OpenRouter API (OpenAI-compatible) |
| Vector memory | ChromaDB |
| Image processing | Pillow |
| Data validation | Pydantic v2 |
| Config | python-dotenv |
| Frontend | Vanilla JavaScript + SSE |

## Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Create a .env file (see Environment Variables below)
cp .env.example .env  # or create manually

# Start the server
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# Or directly
python main.py
```

The app runs on `http://127.0.0.1:8000` with hot-reload enabled.

## Environment Variables

Create a `.env` file in the project root (never commit it — it is gitignored):

```env
OPENROUTER_API_KEY=<your_openrouter_key>
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
MODEL=gpt-4o-mini

# Memory
MEMORY_RETRIEVAL_COUNT=5
MEMORY_DB_PATH=./memory

# Sprite rendering
SPRITE_ASSET_PATH=./static/sprites

# MAS integration (optional)
MAS_PERSISTENT_PATH=<absolute_path_to_MAS_persistent_file>

# Feature flags
USE_TTS=false
DEBUG=false
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Serves `static/index.html` |
| `POST` | `/chat` | Chat endpoint — streams response via SSE |
| `GET` | `/render/{sprite_code}` | Renders and returns a sprite PNG from a code |
| `POST` | `/end-session` | Closes session and saves memory to ChromaDB |
| `GET` | `/memories` | Debug — returns all stored memories as JSON |

### Chat Request Body

```json
{
  "message": "string",
  "history": [{"role": "user|assistant", "content": "string"}]
}
```

The chat endpoint returns a `text/event-stream` (SSE) response. The frontend handles incremental token delivery and sprite code extraction from the stream.

## Key Architecture Concepts

### Streaming + Tool Use Loop

The `/chat` endpoint runs a two-pass loop when tool calls are requested:

1. **Non-streaming pass** — detects if the LLM wants to call a tool.
2. **Tool execution** — dispatches to the appropriate function (e.g. `get_temperature`).
3. **Streaming pass** — sends the final response back as SSE tokens.

If no tools are requested, it goes straight to the streaming pass.

### Memory System (`memory.py`)

Two ChromaDB collections:

- **`conversations`** — LLM-generated summaries stored at session end.
  - Metadata: `{"date": "ISO timestamp", "topics": "comma,separated,tags"}`
  - ID format: `conv_{ISO_timestamp}`

- **`player_facts`** — Discrete facts about the player, upserted by category.
  - Metadata: `{"date": "ISO timestamp", "category": "string"}`
  - ID format: `fact_{category}_{ISO_timestamp}`

Memories are retrieved via semantic similarity and injected into the system prompt at each turn. Call `build_memory_context(message)` to get the injection string.

### Affection System (`mas_affection.py`)

MAS affection levels (numeric range -100 to 1000+):

| Level | Range |
|---|---|
| `BROKEN` | < -10 |
| `DISTRESSED` | -10 to 10 |
| `UPSET` | 10 to 250 |
| `NORMAL` | 250 to 500 |
| `HAPPY` | 500 to 750 |
| `AFFECTIONATE` | 750 to 1000 |
| `ENAMORED` | 1000 to 2000 |
| `LOVE` | 2000+ |

Key behaviors:
- Daily affection cap of **9.0 points** (with bypass flag).
- Gaussian noise is applied to each gain.
- Changes are persisted to MAS's compressed pickle file.

The affection level modulates the system prompt passed to the LLM.

### Sprite System (`sprite/`)

3-stage rendering pipeline:

1. **Parse** (`parser.py`) — Decodes a sprite code string (e.g. `"1ekbsua"`) into a dict of named components (`arms`, `eyes`, `eyebrows`, `mouth`, optional `blush`, `tears`, `sweat`, `emote`, `lean`).
2. **Resolve** (`resolver.py`) — Maps components to an ordered list of PNG paths. Layer order (back-to-front): back hair → chair → body → arms → mid hair → head → table → arms (mid) → body front → blush → front hair → face layers → arms (front).
3. **Composite** (`compositor.py`) — Alpha-composites all layers onto a 1280×850 RGBA canvas using Pillow.

Asset directory structure expected under `SPRITE_ASSET_PATH/monika/`:
```
monika/b/   # base body, arms, head
monika/c/   # clothing
monika/f/   # face layers
monika/h/   # hair
monika/t/   # table / chair
```

### MAS Persistent File (`mas_persistent_tools.py`)

MAS saves game state as a zlib-compressed or uncompressed Python pickle file. This module provides Ren'Py stub classes so the file can be unpickled in a plain Python environment.

Key utilities:
- `load_persistent(path)` — Returns the unpickled persistent object.
- `get_value(persistent, key)` — Safely reads a key.
- `dump_affection(path)` — Prints affection info.
- `dump_session(path)` — Prints session info.

## Code Conventions

### Naming
- **Functions and variables**: `snake_case`
- **Classes**: `PascalCase` (e.g. `MASAffectionManager`, `ChatRequest`)
- **Constants**: `UPPER_CASE` (e.g. `BROKEN`, `MEMORY_RETRIEVAL_COUNT`)
- **Module-level private items**: prefixed with `_` (e.g. `_SPRITE_MAP`, `_decode()`)

### Typing
- Pydantic models are used for all FastAPI request/response schemas.
- Type hints are used in `sprite/` but are inconsistent elsewhere — add them when touching existing code.

### Async
- All FastAPI route handlers and I/O-bound operations use `async`/`await`.
- Blocking I/O (e.g. file reads in MAS utilities, Pillow compositing) should be moved to thread pools if latency becomes a concern.

### Error Handling
- LLM and HTTP calls use `tenacity` for retry logic.
- MAS file loading degrades gracefully (affection disabled if file not found).
- Sprite rendering raises `ValueError` for unrecognized sprite codes.

### Configuration Access
- Always import from `config.py` — never read `os.environ` directly.
- Use `config.log()` for debug-level logging (respects the `DEBUG` flag).

## Adding New LLM Tools

1. Define the tool schema in `tools.py` following the OpenAI function-calling format.
2. Implement the Python function.
3. Register it in the `TOOL_HANDLERS` dispatch dict inside `tools.py`.
4. The tool loop in `main.py` will automatically pick it up.

## Adding New Affection Levels

Edit the `AFFECTION_LEVELS` list and the threshold comparisons in `mas_affection.py`. Ensure the system prompt mapping in `main.py` is updated to handle the new level name.

## Important Files to Understand First

If you are new to the codebase, read these files in order:

1. `config.py` — understand all configuration knobs.
2. `main.py` — the application entry point and request flow.
3. `memory.py` — how conversations are persisted and retrieved.
4. `tools.py` — how tool/function calling works.
5. `sprite/parser.py` → `resolver.py` → `compositor.py` — the rendering pipeline.

## Known Issues / Areas for Improvement

- `main.py` conversation history is stored in-memory and is not thread-safe for multiple simultaneous users. The app assumes a single active user per server process.
- No formal test suite exists. Adding `pytest` tests, especially for the sprite parsing and memory modules, would improve reliability.
- Type hint coverage is incomplete outside of `sprite/`.
- The `get_temperature` tool is hardcoded to a local Raspberry Pi address (`192.168.1.249:5000`) and will fail in other environments.

## Git Workflow

- Main development branch: `master`
- Feature branches follow the pattern: `claude/<description>-<id>`
- Commit messages should be descriptive and imperative (e.g. `Add affection level LOVE to system prompt mapping`).
- Do **not** commit `.env` files, virtual environments, or the `persistent` MAS save file.
