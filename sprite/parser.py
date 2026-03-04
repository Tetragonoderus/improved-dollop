"""
sprite/parser.py

Parses a MAS sprite code string into a dict of named components.
This is a port of the StaticSprite._rip_sprite() logic from sprite.py,
using sprite_map.json as the lookup table.

Input:  sprite code string, e.g. "1ekbsu"
Output: dict of named components, e.g.
    {
        "arms":      "steepling",
        "eyes":      "normal",
        "eyebrows":  "knit",
        "nose":      "def",
        "mouth":     "smug",
        "blush":     "shade",
        "tears":     None,
        "sweat":     None,
        "emote":     None,
        "lean":      None,
        "is_lean":   False,
    }

Raises ValueError for invalid or unrecognised sprite codes.
"""

import json
import os
from pathlib import Path
from dotenv import load_dotenv

# Load the .env file
load_dotenv()

# Fetch the path from environment variables and convert to a Path object
# We use a default fallback (like ".") to avoid errors if the key is missing
SPRITE_ASSET_PATH = Path(os.getenv("SPRITE_ASSET_PATH", "."))

# Load the sprite map once at import time
_MAP_PATH = SPRITE_ASSET_PATH / "sprite_map.json"
with open(_MAP_PATH) as f:
    _SPRITE_MAP = json.load(f)

# Codes that indicate an optional modifier starts here, and
# how many characters that modifier consumes
_OPTIONAL_PREFIXES = {
    "b": ("blush",  2),   # bl, bs, bf
    "t": ("tears",  2),   # ts, td, tp, tu
    "s": ("sweat",  3),   # sdl, sdr
    "e": ("emote",  2),   # ec (unused but present)
    "n": ("nose",   2),   # nd (unused but present)
}


def parse(sprite_code: str) -> dict:
    """
    Parse a sprite code into named components.

    Parameters
    ----------
    sprite_code : str
        A MAS sprite code such as "1eua" or "1ekbsua".

    Returns
    -------
    dict
        Named component values ready for the file path resolver.

    Raises
    ------
    ValueError
        If the code is too short, or contains unrecognised characters.
    """
    code = sprite_code.strip().lower()

    if len(code) < 4:
        raise ValueError(f"Sprite code '{code}' is too short (minimum 4 characters)")

    result = {
        "arms":     None,
        "eyes":     None,
        "eyebrows": None,
        "nose":     "def",   # always default, never specified in code
        "mouth":    None,
        "blush":    None,
        "tears":    None,
        "sweat":    None,
        "emote":    None,
        "lean":     None,
        "is_lean":  False,
    }

    # ── Position (index 0) ───────────────────────────────────────────────────
    pos_code = code[0]
    arms = _SPRITE_MAP["arms"].get(pos_code)
    if arms is None:
        raise ValueError(f"Unknown pose code '{pos_code}'")

    # Pose 5 is the lean — arms value is a list [lean, arms]
    if isinstance(arms, list):
        result["lean"]    = arms[0]
        result["arms"]    = arms[1]
        result["is_lean"] = True
    else:
        result["arms"] = arms

    # ── Eyes (index 1) ───────────────────────────────────────────────────────
    eye_code = code[1]
    eyes = _SPRITE_MAP["eyes"].get(eye_code)
    if eyes is None:
        raise ValueError(f"Unknown eye code '{eye_code}'")
    result["eyes"] = eyes

    # ── Eyebrows (index 2) ───────────────────────────────────────────────────
    brow_code = code[2]
    brows = _SPRITE_MAP["eyebrows"].get(brow_code)
    if brows is None:
        raise ValueError(f"Unknown eyebrow code '{brow_code}'")
    result["eyebrows"] = brows

    # ── Mouth (last character) ───────────────────────────────────────────────
    mouth_code = code[-1]
    mouth = _SPRITE_MAP["mouth"].get(mouth_code)
    if mouth is None:
        raise ValueError(f"Unknown mouth code '{mouth_code}'")
    result["mouth"] = mouth

    # ── Optional modifiers (everything between index 3 and last) ─────────────
    middle = code[3:-1]
    i = 0
    while i < len(middle):
        prefix = middle[i]
        if prefix not in _OPTIONAL_PREFIXES:
            raise ValueError(f"Unknown modifier prefix '{prefix}' in '{code}'")

        field, length = _OPTIONAL_PREFIXES[prefix]
        token = middle[i:i + length]   # e.g. "bl", "ts", "sdl"

        value = _SPRITE_MAP.get(field, {}).get(token)
        if value is None:
            raise ValueError(f"Unknown {field} code '{token}' in '{code}'")

        if result[field] is not None:
            raise ValueError(f"Duplicate {field} modifier in '{code}'")

        result[field] = value
        i += length

    return result

if __name__ == "__main__":
    # This only runs when you do: python your_file.py
    print("--- Diagnostic Check ---")
    print(f"Base Path: {SPRITE_ASSET_PATH}")
    print(f"Full Map Path: {_MAP_PATH}")
    print(f"File exists? {_MAP_PATH.exists()}")
    print(parse('1eua'))
