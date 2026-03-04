import os
from pathlib import Path
from dotenv import load_dotenv, set_key as _dotenv_set_key

load_dotenv()

# --- API ---
API_KEY  = os.getenv("OPENROUTER_API_KEY")
API_BASE = os.getenv("OPENROUTER_BASE_URL")        # e.g. https://openrouter.ai/api/v1
MODEL    = os.getenv("MODEL", "gpt-4o-mini")

# --- Memory ---
# How many relevant memories to retrieve and inject per conversation turn
MEMORY_RETRIEVAL_COUNT = int(os.getenv("MEMORY_RETRIEVAL_COUNT", 5))
# Where ChromaDB stores its data
MEMORY_DB_PATH = os.getenv("MEMORY_DB_PATH", "./memory")

# --- Sprites ---
# Path to the extracted MAS sprite layer assets
SPRITE_ASSET_PATH = os.getenv("SPRITE_ASSET_PATH", "./static/sprites")

# --- MAS Integration ---
# Path to the MAS persistent file if you want to read player state from it
MAS_PERSISTENT_PATH = os.getenv("MAS_PERSISTENT_PATH", "")

# --- TTS ---
USE_TTS = os.getenv("USE_TTS", "false").lower() == "true"

# --- Debug ---
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

def log(x):
    if DEBUG:
        print(x)


_DOTENV_PATH = str(Path(__file__).parent / ".env")


def save_config(api_key: str | None = None, model: str | None = None) -> dict:
    """Persist api_key and/or model to .env and return the updated values."""
    Path(_DOTENV_PATH).touch()
    if api_key:
        _dotenv_set_key(_DOTENV_PATH, "OPENROUTER_API_KEY", api_key)
    if model:
        _dotenv_set_key(_DOTENV_PATH, "MODEL", model)
    load_dotenv(_DOTENV_PATH, override=True)
    return {
        "api_key": os.getenv("OPENROUTER_API_KEY", ""),
        "model": os.getenv("MODEL", "gpt-4o-mini"),
    }


def get_config_values() -> dict:
    """Return the current runtime config values from environment."""
    return {
        "api_key": os.getenv("OPENROUTER_API_KEY", ""),
        "model": os.getenv("MODEL", "gpt-4o-mini"),
    }