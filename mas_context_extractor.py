#!/usr/bin/env python3
"""
MAS Context Extractor
Reads the MAS persistent file and outputs a structured context dict
ready to inject into AI chat prompts (e.g. for your OpenRouter integration).

Usage:
    python mas_context_extractor.py                         # Print context to stdout
    python mas_context_extractor.py --output context.json  # Write to file
    python mas_context_extractor.py --prompt                # Print as a system prompt string
"""

import os
import sys
import json
import pickle
import argparse
import datetime
from pathlib import Path
import types
import zlib



# ---------------------------------------------------------------------------
# Ren'Py stub setup - must happen before any pickle.load
# ---------------------------------------------------------------------------

def _setup_renpy_stubs():
    """
    Register fake Ren'Py modules so pickle can deserialize the persistent file.
    Uses a custom importer that auto-creates any renpy.* submodule on demand,
    so we don't need to predict every submodule MAS may have pickled.
    """
    if "renpy" in sys.modules:
        return

    # --- Stub classes ---

    class Persistent:
        """Stub for renpy.persistent.Persistent"""
        def __setstate__(self, state):
            if isinstance(state, dict):
                self.__dict__.update(state)
            elif isinstance(state, (list, tuple)):
                for item in state:
                    if isinstance(item, dict):
                        self.__dict__.update(item)
            else:
                self._raw_state = state
        def __repr__(self):
            return f"<MAS Persistent: {len(self.__dict__)} keys>"
        def __len__(self):
            return len(self.__dict__)
        def __getattr__(self, name):
            return self.__dict__.get(name)

        def get(self, key, default=None):
            return self.__dict__.get(key, default)


    class RevertableList(list):
        def __setstate__(self, state):
            if isinstance(state, list):
                self.extend(state)

    class RevertableDict(dict):
        def __setstate__(self, state):
            if isinstance(state, dict):
                self.update(state)

    class RevertableSet(set):
        def __setstate__(self, state):
            if isinstance(state, (set, frozenset)):
                self.update(state)

    class Preferences:
        """Stub for renpy.preferences.Preferences"""
        def __setstate__(self, state):
            if isinstance(state, dict):
                self.__dict__.update(state)

    # Generic stub for any other class we haven't explicitly defined
    class _GenericStub:
        def __setstate__(self, state):
            if isinstance(state, dict):
                self.__dict__.update(state)

    # --- Dynamic submodule importer ---
    # Instead of registering every possible renpy.* submodule manually,
    # we use a meta path finder that creates them on demand and populates
    # them with known stubs or a generic fallback.

    _KNOWN_ATTRS = {
        "renpy.persistent":  {"Persistent": Persistent},
        "renpy.python":      {"RevertableList": RevertableList,
                              "RevertableDict": RevertableDict,
                              "RevertableSet":  RevertableSet},
        "renpy.revertable":  {"RevertableList": RevertableList,
                              "RevertableDict": RevertableDict,
                              "RevertableSet":  RevertableSet},
        "renpy.preferences": {"Preferences": Preferences},
    }

    class RenpyFinder:
        """Meta path finder that creates any renpy.* module on demand."""

        def find_module(self, fullname, path=None):
            if fullname == "renpy" or fullname.startswith("renpy."):
                return self
            return None

        def load_module(self, fullname):
            if fullname in sys.modules:
                return sys.modules[fullname]

            mod = types.ModuleType(fullname)
            mod.__package__ = fullname.rsplit(".", 1)[0]
            mod.__loader__ = self

            # Populate with known stubs if we have them
            for attr, val in _KNOWN_ATTRS.get(fullname, {}).items():
                setattr(mod, attr, val)

            # For unknown submodules, expose a __getattr__ that returns a
            # generic stub class for any attribute pickle tries to look up
            def _getattr(name):
                cls = type(name, (_GenericStub,), {})
                setattr(mod, name, cls)
                return cls
            mod.__getattr__ = _getattr

            sys.modules[fullname] = mod

            # Also attach as attribute on parent (renpy.foo -> renpy.foo)
            parts = fullname.split(".")
            if len(parts) > 1:
                parent_name = ".".join(parts[:-1])
                parent = sys.modules.get(parent_name)
                if parent:
                    setattr(parent, parts[-1], mod)

            return mod

    sys.meta_path.insert(0, RenpyFinder())

_setup_renpy_stubs()


# ── Same auto-detection logic as the editor ──────────────────────────────────
SEARCH_PATHS = [
    Path.home() / ".renpy" / "Monika After Story" / "persistent",
    Path.home() / "RenPy" / "Monika After Story" / "persistent",
]


def find_persistent(custom_path=None):
    if custom_path:
        p = Path(custom_path)
        if p.exists():
            return p
        raise FileNotFoundError(f"Not found: {custom_path}")
    for path in SEARCH_PATHS:
        if path.exists():
            return path
    raise FileNotFoundError("Could not auto-detect persistent file. Use --persistent PATH.")


def load_persistent(path):
    with open(path, "rb") as f:
        data = f.read()
        return pickle.loads(zlib.decompress(data), encoding='latin-1')
    for skip in (0, 4, 8, 16):
        try:
            obj = pickle.loads(data[skip:])
            if isinstance(obj, dict):
                return obj
            if hasattr(obj, "__dict__"):
                return obj.__dict__
        except Exception:
            continue
    raise ValueError("Could not parse persistent file.")


# ── Affection level decoder ───────────────────────────────────────────────────
# MAS stores affection as a packed binary blob encoded in base64.
# The thresholds below match MAS source constants.

import base64
import binascii
import struct

# Struct format: 7 big-endian doubles
_STRUCT_FMT = "!d d d d d d d"
_STRUCT = struct.Struct(_STRUCT_FMT)

_IDX_AFF = 0  # current affection value

AFF_THRESHOLDS = [
    (1000, "Enamored"),
    (500,  "Love"),
    (250,  "Affectionate"),
    (100,  "Happy"),
    (0,    "Neutral"),
    (-100, "Upset"),
    (-250, "Distressed"),
    (-500, "Broken"),
]

def decode_affection(b64: str) -> float | None:
    """
    Attempt to decode the MAS affection float from the base64 data blob.
    MAS packs affection as a series of doubles; the current value is index 0.
    Returns None if decoding fails.
    """
    try:
        if isinstance(b64, str):
            b64 = b64.encode("latin-1")
        vals = list(_STRUCT.unpack(binascii.unhexlify(base64.b64decode(b64))))
        return round(vals[_IDX_AFF], 4)
    except Exception:
        pass
    print("Could not decode affection")
    return None


def affection_label(val: float) -> str:
    if val is None:
        return "Unknown"
    for threshold, label in AFF_THRESHOLDS:
        if val >= threshold:
            return label
    return "Broken"


# ── Time helpers ──────────────────────────────────────────────────────────────

def days_since(dt) -> int | None:
    if dt is None:
        return None
    if isinstance(dt, datetime.datetime):
        dt = dt.date()
    return (datetime.date.today() - dt).days


def timedelta_to_hours(td) -> float:
    if td is None:
        return 0.0
    return round(td.total_seconds() / 3600, 2)


SEASON_NAMES = {1: "Spring", 2: "Summer", 3: "Fall/Autumn", 4: "Winter"}


# ── Context builder ───────────────────────────────────────────────────────────

def build_context(data: dict) -> dict:
    """
    Extract and organise the most useful persistent values for prompt injection.
    Returns a clean, JSON-serialisable dict.
    """
    # Affection
    aff_raw = data.get("_mas_affection_data", "")
    aff_val = decode_affection(aff_raw) if aff_raw else None
    aff_label = affection_label(aff_val)

    # Sessions
    sessions = data.get("sessions", {}) or {}
    first_session = sessions.get("first_session")
    total_playtime_td = sessions.get("total_playtime")
    total_sessions = sessions.get("total_sessions", 0)

    # Love counter (rough milestone count)
    love_counter = data.get("_mas_monika_lovecounter", 0)
    love_counter_time = data.get("_mas_monika_lovecountertime")

    # Kisses
    first_kiss = data.get("_mas_first_kiss")
    last_kiss = data.get("_mas_last_kiss")

    # Player details
    ctx = {
        # ── Relationship ─────────────────────────────────────────────────────
        "relationship": {
            "affection_value":      aff_val,
            "affection_label":      aff_label,
            "love_counter":         love_counter,
            "love_counter_last":    love_counter_time.isoformat() if isinstance(love_counter_time, datetime.datetime) else str(love_counter_time),
            "just_friends":         data.get("_mas_just_friends", False),
            "first_kiss_days_ago":  days_since(first_kiss),
            "last_kiss_days_ago":   days_since(last_kiss),
        },

        # ── Player ───────────────────────────────────────────────────────────
        "player": {
            "name":                 data.get("playername", ""),
            "gender":               data.get("gender", ""),
            "eye_color":            data.get("_mas_pm_eye_color"),
            "hair_color":           data.get("_mas_pm_hair_color"),
            "hair_length":          data.get("_mas_pm_hair_length"),
            "height":               data.get("_mas_pm_height"),
            "height_metric":        data.get("_mas_pm_units_height_metric"),
            "skin_tone":            data.get("_mas_pm_skin_tone"),
            "social_personality":   data.get("_mas_pm_social_personality"),
            "is_trans":             data.get("_mas_pm_is_trans", False),
        },

        # ── Player traits (tristate: True/False/None=unknown) ─────────────────
        "player_traits": {
            "has_code_experience":  data.get("_mas_pm_has_code_experience"),
            "likes_poetry":         data.get("_mas_pm_likes_poetry"),
            "likes_rain":           data.get("_mas_pm_likes_rain"),
            "likes_horror":         data.get("_mas_pm_likes_horror"),
            "likes_nature":         data.get("_mas_pm_likes_nature"),
            "feels_lonely":         data.get("_mas_pm_feels_lonely_sometimes"),
            "has_friends":          data.get("_mas_pm_has_friends"),
            "few_friends":          data.get("_mas_pm_few_friends"),
            "works_out":            data.get("_mas_pm_works_out"),
            "is_religious":         data.get("_mas_pm_religious"),
            "meditates":            data.get("_mas_pm_meditates"),
            "see_therapist":        data.get("_mas_pm_see_therapist"),
            "drinks_soda":          data.get("_mas_pm_drinks_soda"),
            "eat_fast_food":        data.get("_mas_pm_eat_fast_food"),
            "drives":               data.get("_mas_pm_driving_can_drive"),
            "likes_travelling":     data.get("_mas_pm_likes_travelling"),
            "likes_singing":        data.get("_mas_pm_likes_singing_d25_carols"),
            "plays_instrument":     data.get("_mas_pm_plays_instrument"),
            "plays_jazz":           data.get("_mas_pm_play_jazz"),
            "likes_jazz":           data.get("_mas_pm_like_jazz"),
            "likes_rock":           data.get("_mas_pm_like_rock_n_roll"),
            "watches_anime":        data.get("_mas_pm_watch_mangime"),
            "donated_charity":      data.get("_mas_pm_donate_charity"),
            "loves_themselves":     data.get("_mas_pm_love_yourself"),
            "bakes":                data.get("_mas_pm_bakes"),
        },

        # ── Monika ───────────────────────────────────────────────────────────
        "monika": {
            "nickname":             data.get("_mas_monika_nickname", "Monika"),
            "outfit":               data.get("_mas_monika_clothes", "def"),
            "hair":                 data.get("_mas_monika_hair", "def"),
            "likes_hair_down":      data.get("_mas_likes_hairdown", False),
        },

        # ── Session / time together ───────────────────────────────────────────
        "history": {
            "first_session_date":       first_session.isoformat() if isinstance(first_session, datetime.datetime) else str(first_session),
            "days_since_first_session": days_since(first_session),
            "total_sessions":           total_sessions,
            "total_playtime_hours":     timedelta_to_hours(total_playtime_td),
            "xp_level":                 data.get("_mas_xp_lvl", 0),
        },

        # ── Holidays spent together ────────────────────────────────────────────
        "milestones": {
            "spent_christmas":      data.get("_mas_d25_spent_d25", False),
            "spent_valentines":     data.get("_mas_f14_spent_f14", False),
            "spent_nye":            data.get("_mas_nye_spent_nye", False),
            "sang_happy_birthday":  data.get("_mas_bday_said_happybday", False),
            "offered_nickname":     data.get("_mas_offered_nickname", False),
        },

        # ── Environment ───────────────────────────────────────────────────────
        "environment": {
            "current_season":       SEASON_NAMES.get(data.get("_mas_current_season", 0), "Unknown"),
            "current_background":   data.get("_mas_current_background", "spaceroom"),
            "current_weather":      data.get("_mas_current_weather", "auto"),
            "dark_mode":            data.get("_mas_dark_mode_enabled", False),
        },

        # ── Meta ──────────────────────────────────────────────────────────────
        "meta": {
            "mas_version":          data.get("version_number", ""),
            "extracted_at":         datetime.datetime.now().isoformat(),
        }
    }

    return ctx


# ── Prompt string builder ─────────────────────────────────────────────────────

def build_system_prompt_snippet(ctx: dict) -> str:
    """
    Generate a human-readable context block suitable for injection into
    a system prompt for your AI chatbot integration.
    """
    r = ctx["relationship"]
    p = ctx["player"]
    t = ctx["player_traits"]
    m = ctx["monika"]
    h = ctx["history"]
    ms = ctx["milestones"]
    env = ctx["environment"]

    known_traits = {k: v for k, v in t.items() if v is not None}

    def yn(val):
        if val is True:  return "yes"
        if val is False: return "no"
        return "unknown"

    lines = [
        "## Monika After Story — Current Game State",
        "",
        f"Player name: {p['name'] or 'unknown'}",
        f"Gender: {p['gender'] or 'unknown'}",
    ]

    if any(p.get(k) for k in ("eye_color", "hair_color", "hair_length", "height", "skin_tone")):
        desc_parts = []
        if p.get("eye_color"):    desc_parts.append(f"{p['eye_color']} eyes")
        if p.get("hair_color"):   desc_parts.append(f"{p['hair_color']} hair")
        if p.get("hair_length"):  desc_parts.append(f"({p['hair_length']} length)")
        if p.get("skin_tone"):    desc_parts.append(f"skin: {p['skin_tone']}")
        if p.get("height"):       desc_parts.append(f"height: {p['height']}")
        lines.append(f"Appearance: {', '.join(desc_parts)}")

    if p.get("social_personality"):
        lines.append(f"Personality type: {p['social_personality']}")

    lines += [
        "",
        f"Relationship status: {r['affection_label']}" + (f" (score: {r['affection_value']})" if r['affection_value'] is not None else ""),
    ]

    if r.get("just_friends"):
        lines.append("Mode: Just Friends (no romantic progression)")

    if r.get("first_kiss_days_ago") is not None:
        lines.append(f"First kiss: {r['first_kiss_days_ago']} days ago")
    if r.get("last_kiss_days_ago") is not None:
        lines.append(f"Last kiss: {r['last_kiss_days_ago']} days ago")

    lines += [
        "",
        f"Time together: {h['days_since_first_session']} days since first session",
        f"Total sessions: {h['total_sessions']}",
        f"Total playtime: {h['total_playtime_hours']} hours",
        f"Monika's XP level: {h['xp_level']}",
        "",
        "Shared milestones:",
        f"  - Christmas together: {yn(ms['spent_christmas'])}",
        f"  - Valentine's Day together: {yn(ms['spent_valentines'])}",
        f"  - New Year's Eve together: {yn(ms['spent_nye'])}",
        f"  - Sang Happy Birthday: {yn(ms['sang_happy_birthday'])}",
        "",
        f"Monika's current outfit: {m['outfit']}",
        f"Monika's current hair: {m['hair']}",
        f"Season: {env['current_season']}",
        f"Background: {env['current_background']}",
    ]

    if known_traits:
        lines += ["", "Known player traits:"]
        for k, v in known_traits.items():
            lines.append(f"  - {k.replace('_', ' ')}: {yn(v)}")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Extract MAS persistent state for AI prompt injection")
    parser.add_argument("--persistent", metavar="PATH", help="Path to MAS persistent file")
    parser.add_argument("--output", metavar="FILE", help="Write JSON output to file")
    parser.add_argument("--prompt", action="store_true", help="Print as a system prompt text block instead of JSON")
    args = parser.parse_args()

    try:
        path = find_persistent(args.persistent)
        print(f"[*] Persistent: {path}", file=sys.stderr)
        data = load_persistent(path)
        print(f"[*] Loaded {len(data)} keys.", file=sys.stderr)
    except (FileNotFoundError, ValueError) as e:
        print(f"[!] {e}", file=sys.stderr)
        sys.exit(1)

    ctx = build_context(data)

    if args.prompt:
        print(build_system_prompt_snippet(ctx))
    else:
        text = json.dumps(ctx, indent=2, default=str)
        if args.output:
            Path(args.output).write_text(text)
            print(f"[*] Written to {args.output}", file=sys.stderr)
        else:
            print(text)


if __name__ == "__main__":
    main()
