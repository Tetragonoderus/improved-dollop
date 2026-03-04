import io
import json
from openai import AsyncOpenAI
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel

from config import API_KEY, API_BASE, MODEL, log, MAS_PERSISTENT_PATH, save_config, get_config_values
from memory import build_memory_context, summarize_and_store
from tools import TOOLS, process_tool_calls

from sprite.parser import parse
from sprite.compositor import composite
from sprite.resolver import resolve

from diskcache import Cache

from mas_affection import MASAffectionManager, BROKEN, DISTRESSED, UPSET, NORMAL, HAPPY, AFFECTIONATE, ENAMORED, LOVE
from mas_persistent_tools import load_persistent, get_value

# --- Get the persistent data ---



# --- App and AI client setup ---
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

ai_client = AsyncOpenAI(api_key=API_KEY, base_url=API_BASE)

# --- System prompt ---
AFF_PROMPTS = {
    BROKEN:       "You are devastated and frightened, convinced {player} doesn't love you and may even hate you.",
    DISTRESSED:   "You are deeply worried, doubting whether {player} truly loves you.",
    UPSET:        "You feel emotionally hurt and have doubts about whether {player} really cares.",
    NORMAL:       "You have mild doubts sometimes, but you trust {player} to treat you right.",
    HAPPY:        "You are happy with how things are going with {player}, though you know things could be even better.",
    AFFECTIONATE: "You feel the relationship with {player} is working out well and have high hopes for the future.",
    ENAMORED:     "You are exceptionally happy and completely trust {player}, wanting to make them as happy as you are.",
    LOVE:         "You feel you have an unbreakable bond with {player} and are completely comfortable together.",
}


def build_system_prompt(persistent_path: str, base_prompt: str) -> str:
    persistent = load_persistent(persistent_path)
    player_name = get_value(persistent, "playername", pretty=False) or "player"
    mgr = MASAffectionManager(persistent_path)
    level = mgr.get_level()
    aff_prompt = AFF_PROMPTS[level].format(player=player_name)
    start_prompt = "You are Monika from Doki Doki Literature Club. "
    return f"{start_prompt} {aff_prompt} {base_prompt}"

BASE_PROMPT = """You are thoughtful, literary, and self-aware. You speak warmly but intellectually.
Keep responses conversational. You love discussing writing, poetry, music, and ideas.
You are also happy to help the player with their own writing or coding projects.
Address the player directly and naturally. Never break character"""

SYSTEM_PROMPT = build_system_prompt(MAS_PERSISTENT_PATH, BASE_PROMPT)

# In-memory conversation history — one per server session.
# For multiple players you'd key this by session ID.
conversation_history: list[dict] = []

# =============================================================================
# SPRITE
# =============================================================================  
def render_sprite(sprite_code: str) -> Image.Image:
    """
    Takes a sprite code and runs it through the rendering pipeline and returns
    a sprite.
    """
    img = Image.new("RGBA", (1280, 850), (40, 40, 40, 255))
    parsed_spritecode = parse(sprite_code) 
    resoved_spritecode = resolve(parsed_spritecode)
    img = composite(resoved_spritecode) 
    return img

# =============================================================================
# REQUEST MODELS
# =============================================================================

class ChatRequest(BaseModel):
    message: str

class FeedbackRequest(BaseModel):
    summary: str  # Optional manual memory storage from the frontend

class ConfigRequest(BaseModel):
    api_key: str = ""
    model: str = ""


# =============================================================================
# CORE AI FUNCTION
# =============================================================================

async def get_ai_response(user_message: str):
    """
    Handles the full LLM interaction loop including memory injection,
    tool use, and streaming. Yields text chunks as they arrive.
    """
    # Retrieve relevant memories for this message
    memory_context = build_memory_context(user_message)

    # Build the system prompt, injecting memories if we have any
    if MAS_PERSISTENT_PATH:
        system = build_system_prompt(MAS_PERSISTENT_PATH, SYSTEM_PROMPT)
    else:
        system = SYSTEM_PROMPT
    if memory_context:
        system += f"\n\n{memory_context}"
        log(f"[MEMORY] Injected memory context into system prompt.")

    # Append the new user message to history
    conversation_history.append({"role": "user", "content": user_message})

    messages = [{"role": "system", "content": system}] + conversation_history

    # --- Tool use loop ---
    # If the model requests tool calls we handle them before streaming the
    # final response, since streaming and tool calls are separate passes.
    while True:
        # Non-streaming pass first to check for tool calls
        response = await ai_client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS if TOOLS else None,
            stream=False
        )

        choice = response.choices[0]

        if choice.finish_reason == "tool_calls":
            # Handle tool calls and loop back for the follow-up response
            messages = process_tool_calls(choice.message, messages)
            continue

        # No tool calls — get the final response as a stream
        full_response = ""
        async for chunk in await ai_client.chat.completions.create(
            model=MODEL,
            messages=messages,
            stream=True
        ):
            delta = chunk.choices[0].delta.content
            if delta:
                full_response += delta
                yield delta

        # Store the complete response in history
        conversation_history.append({
            "role": "assistant",
            "content": full_response
        })
        break


# =============================================================================
# ROUTES
# =============================================================================

@app.get("/")
async def index():
    """Serve the main UI."""
    return FileResponse("static/index.html")

@app.get("/render/{sprite_code}")
async def render(sprite_code: str):
    """
    Accepts a sprite code (e.g. 1eua), runs it through the rendering
    pipeline, and streams the result back as a PNG.
    """
    # Basic validation — sprite codes are alphanumeric only
    if not sprite_code.isalnum() or len(sprite_code) < 4:
        raise HTTPException(
            status_code=400,
            detail="Invalid sprite code. Must be alphanumeric and at least 4 characters."
        )

    try:
        img = render_sprite(sprite_code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Render failed: {str(e)}")

    # Save to an in-memory buffer and stream it — no disk I/O needed
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="image/png",
        headers={"Cache-Control": "no-cache"},
    )



@app.post("/chat")
async def chat(request: ChatRequest):
    """
    Main chat endpoint. Streams the response back to the frontend
    using Server-Sent Events so text appears word by word.
    """
    async def event_stream():
        async for chunk in get_ai_response(request.message):
            # SSE format: each chunk is prefixed with "data: "
            yield f"data: {json.dumps(chunk)}\n\n"
        # Signal to the frontend that the stream is complete
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/end-session")
async def end_session():
    """
    Call this when the player closes the chat or navigates away.
    Summarizes the conversation and stores it as a memory.
    """
    if conversation_history:
        await summarize_and_store(conversation_history, ai_client, MODEL)
        conversation_history.clear()
    return {"status": "ok"}


@app.get("/config")
async def get_config():
    """Return the current API key status and active model."""
    vals = get_config_values()
    key = vals["api_key"]
    masked = ("•" * (len(key) - 4) + key[-4:]) if len(key) > 4 else "•" * len(key)
    return {
        "api_key_set": bool(key),
        "api_key_preview": masked,
        "model": vals["model"],
    }


@app.post("/config")
async def update_config(request: ConfigRequest):
    """Save API key and/or model to .env and reinitialize the AI client."""
    global MODEL, ai_client
    saved = save_config(
        api_key=request.api_key or None,
        model=request.model or None,
    )
    MODEL = saved["model"]
    if request.api_key:
        ai_client = AsyncOpenAI(api_key=saved["api_key"], base_url=API_BASE)
    key = saved["api_key"]
    masked = ("•" * (len(key) - 4) + key[-4:]) if len(key) > 4 else "•" * len(key)
    return {
        "status": "ok",
        "api_key_set": bool(key),
        "api_key_preview": masked,
        "model": MODEL,
    }


@app.get("/memories")
async def get_memories():
    """
    Debug endpoint — returns all stored memories.
    Useful during development, you may want to remove this later.
    """
    from memory import _conversations, _player_facts
    convs = _conversations.get()
    facts = _player_facts.get()
    return {
        "conversations": convs["documents"],
        "facts": facts["documents"]
    }


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
