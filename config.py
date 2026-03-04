import os
from dotenv import load_dotenv

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