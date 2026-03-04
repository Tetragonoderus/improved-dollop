"""
sprite/resolver.py

Maps parsed sprite components to ordered lists of PNG file paths.
This replicates the _rk_sitting() layer ordering logic from
sprite-chart-matrix.rpy, but as plain Python.

Input:  dict from parser.parse()
Output: list of Path objects in render order (back to front)

You will need to:
1. Set SPRITE_ASSET_PATH to point at your MAS game/mod_assets directory.
2. Fill in the path prefix constants once you've confirmed them
   from the MAS source (sprite-chart.rpy or sprite-chart-matrix.rpy).
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

#for testing
#from parser import parse

# ── Configure these ───────────────────────────────────────────────────────────
# Fetch the path from environment variables and convert to a Path object
# We use a default fallback (like ".") to avoid errors if the key is missing
load_dotenv()
SPRITE_ASSET_PATH = Path(os.getenv("SPRITE_ASSET_PATH", "."))

# Path prefix constants — confirm these from the MAS source
# These are best guesses based on the rendering code; verify before use.
B_MAIN   = SPRITE_ASSET_PATH / "monika/b"          # base body/arms/head
C_MAIN   = SPRITE_ASSET_PATH / "monika/c"        # clothing
F_MAIN   = SPRITE_ASSET_PATH / "monika/f"           # face layers
H_MAIN   = SPRITE_ASSET_PATH / "monika/h"           # hair
T_MAIN   = SPRITE_ASSET_PATH / "monika/t"          # table/chair

FILE_EXT = ".png"

# Default values used when not overridden by the sprite code
DEFAULT_CLOTHES = "def"    # default outfit name
DEFAULT_HAIR    = "def"       # default hair name
DEFAULT_TABLE   = "def"       # default table/chair name
# ─────────────────────────────────────────────────────────────────────────────


def resolve(components: dict, clothes: str = DEFAULT_CLOTHES, hair: str = DEFAULT_HAIR) -> list[Path]:
    """
    Resolve a parsed components dict into an ordered list of PNG paths.

    The list is in back-to-front render order — paste them onto a canvas
    in sequence and the last item ends up on top.

    Parameters
    ----------
    components : dict
        Output of sprite.parser.parse()
    clothes : str
        Clothing variant name (default: "school")
    hair : str
        Hair variant name (default: "def")

    Returns
    -------
    list[Path]
        Ordered list of PNG file paths. Non-existent paths are filtered out
        so optional layers that have no file simply don't appear.
    """
    arms     = components["arms"]
    eyes     = components["eyes"]
    eyebrows = components["eyebrows"]
    nose     = components["nose"]
    mouth    = components["mouth"]
    blush    = components["blush"]
    tears    = components["tears"]
    sweat    = components["sweat"]
    emote    = components["emote"]
    lean     = components["lean"]
    is_lean  = components["is_lean"]

    layers: list[Optional[Path]] = []

    # ── Back hair ─────────────────────────────────────────────────────────────
    layers.append(_hair_path(hair, "0", lean))
    full_path = (_hair_path(hair, "0", lean))
    # DEBUG: Print the absolute truth


    # ── Chair ─────────────────────────────────────────────────────────────────
    layers.append(T_MAIN / f"chair-{DEFAULT_TABLE}{FILE_EXT}")

    # ── Base body back + clothing body back ───────────────────────────────────
    layers.append(_base_body_path("0", lean))
    layers.append(_clothing_body_path(clothes, "0", lean))
    
    # ── Base arms back + clothing arms back ───────────────────────────────────
    layers.append(_base_arms_path(arms, "0", lean))
    layers.append(_clothing_arms_path(clothes, arms, "0", lean))
    
    # ── Mid hair ──────────────────────────────────────────────────────────────
    layers.append(_hair_path(hair, "mid", lean))

    # ── Head ──────────────────────────────────────────────────────────────────
    layers.append(_head_path(lean))

    # ── Table ─────────────────────────────────────────────────────────────────
    layers.append(T_MAIN / f"table-{DEFAULT_TABLE}{FILE_EXT}")

    # ── Base arms middle + clothing arms middle ?crossed ───────────────────────────────
    layers.append(_base_arms_path(arms, "5", lean))
    layers.append(_clothing_arms_path(clothes, arms, "5", lean))

    # ── Base body front + clothing body front (boobs layer) ───────────────────
    layers.append(_base_body_path("1", lean))
    layers.append(_clothing_body_path(clothes, "1", lean))


    # ── Blush (goes under front hair) ─────────────────────────────────────────
    if blush:
        layers.append(_face_path("blush", blush, lean))

    # ── Front hair ────────────────────────────────────────────────────────────
    layers.append(_hair_path(hair, "10", lean))


    # ── Face (eyes, eyebrows, nose, mouth, tears, sweat, emote) ──────────────
    layers.append(_face_path("eyes", eyes, lean))
    layers.append(_face_path("eyebrows", eyebrows, lean))
    layers.append(_face_path("nose", nose, lean))
    layers.append(_face_path("mouth", mouth, lean))

    #print("DEBUG")
    #full_path = (_face_path("mouth", mouth, lean))
    #print(f"DEBUG: Attempting to load: {full_path.resolve()}")
    #print(f"DEBUG: Does it exist?      {full_path.exists()}")
    #print(f"DEBUG: Attempting to load: {full_path.resolve()}")



    if tears:
        # Tears may have eye-specific variants — see MOD_MAP in sprite_map.json
        layers.append(_face_path("tears", tears, lean))
    if sweat:
        layers.append(_face_path("sweat", sweat, lean))
    if emote:
        layers.append(_face_path("emote", emote, lean))

    # ── Base arms front + clothing arms front ?steepling ─────────────────────────────────
    layers.append(_base_arms_path(arms, "10", lean))
    layers.append(_clothing_arms_path(clothes, arms, "10", lean))
    


    # Filter to only paths that actually exist on disk
    return [p for p in layers if p is not None and p.exists()]


# ── Path builder helpers ──────────────────────────────────────────────────────
# These are best guesses — adjust once you've confirmed the exact
# file naming convention from the MAS assets.

def _lean_prefix(lean: Optional[str]) -> str:
    return f"leaning-{lean}-" if lean else ""


def _base_body_path(section: str, lean: Optional[str]) -> Path:
    pfx = _lean_prefix(lean)
    return B_MAIN / f"body-{pfx}def-{section}{FILE_EXT}"


def _base_arms_path(arms: str, section: str, lean: Optional[str]) -> Path:
    pfx = _lean_prefix(lean)
    return B_MAIN / f"arms-{pfx}{arms}-{section}{FILE_EXT}"


def _clothing_body_path(clothes: str, section: str, lean: Optional[str]) -> Path:
    pfx = _lean_prefix(lean)
    return C_MAIN / clothes / f"body-{pfx}def-{section}{FILE_EXT}"


def _clothing_arms_path(clothes: str, arms: str, section: str, lean: Optional[str]) -> Path:
    pfx = _lean_prefix(lean)
    return C_MAIN / clothes / f"arms-{pfx}{arms}-{section}{FILE_EXT}"


def _hair_path(hair: str, layer: str, lean: Optional[str]) -> Path:
    pfx = _lean_prefix(lean)
    return H_MAIN / hair / f"{pfx}{layer}{FILE_EXT}"


def _head_path(lean: Optional[str]) -> Path:
    pfx = _lean_prefix(lean)
    return B_MAIN / f"{pfx}head{FILE_EXT}"


def _face_path(feature: str, value: str, lean: Optional[str]) -> Path:
    pfx = _lean_prefix(lean)
    return F_MAIN / f"face-{pfx}{feature}-{value}{FILE_EXT}"

if __name__ == "__main__":
    test_data = parse('1eua')
    success = resolve(test_data)
    #print(f"Test complete. Status: {success}")
