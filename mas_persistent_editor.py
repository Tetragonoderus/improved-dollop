#!/usr/bin/env python3
"""
MAS Persistent File Editor
A testing utility to read and modify Monika After Story persistent save data.
Useful for injecting values like affection, dates, and player info into chat prompts.

Usage:
    python mas_persistent_editor.py                  # Interactive mode
    python mas_persistent_editor.py --dump           # Dump key values to JSON
    python mas_persistent_editor.py --set KEY VALUE  # Set a specific key
"""

import os
import sys
import json
import pickle
import struct
import base64
import binascii
import argparse
import datetime
from pathlib import Path
from copy import deepcopy


# ── Common MAS persistent file locations ────────────────────────────────────
SEARCH_PATHS = [
    Path.home() / ".renpy" / "MonikaAfterStory" / "persistent",
    Path.home() / "RenPy" / "MonikaAfterStory" / "persistent",
    Path("/home") / os.environ.get("USER", "") / "MonikaModDev" / "Monika After Story" / "game" / "saves" / "persistent",
]


# ── Keys of interest for chat prompt injection ───────────────────────────────
TRACKED_KEYS = {
    # Affection / relationship
    "_mas_affection_data":              "Affection data (base64 encoded)",
    "_mas_monika_lovecounter":          "Love counter (int)",
    "_mas_monika_lovecountertime":      "Last love counter time (datetime)",
    "_mas_affection_version":           "Affection version",

    # Player info
    "playername":                       "Player name",
    "gender":                           "Player gender (M/F)",
    "_mas_monika_nickname":             "Monika's nickname",
    "_mas_pm_is_trans":                 "Player is trans (bool)",
    "_mas_pm_eye_color":                "Player eye color",
    "_mas_pm_hair_color":               "Player hair color",
    "_mas_pm_hair_length":              "Player hair length",
    "_mas_pm_height":                   "Player height",
    "_mas_pm_skin_tone":                "Player skin tone",
    "_mas_pm_social_personality":       "Player social personality",

    # Dates / sessions
    "sessions":                         "Session data (dict with first_session, total_playtime, etc.)",
    "_mas_filereacts_last_aff_gained_reset_date": "Last affection reset date",

    # Relationship milestones
    "_mas_first_kiss":                  "First kiss (datetime or None)",
    "_mas_last_kiss":                   "Last kiss (datetime or None)",
    "_mas_last_monika_ily":             "Last ILY (datetime or None)",
    "_mas_just_friends":                "Just friends mode (bool)",
    "_mas_offered_nickname":            "Monika offered nickname (bool)",

    # Holidays / special events
    "_mas_bday_said_happybday":         "Said happy birthday (bool)",
    "_mas_player_bday":                 "Player birthday (date or None)",
    "_mas_player_confirmed_bday":       "Player confirmed bday (bool)",
    "_mas_d25_spent_d25":               "Spent Christmas together (bool)",
    "_mas_f14_spent_f14":               "Spent Valentine's together (bool)",
    "_mas_nye_spent_nye":               "Spent New Year's Eve together (bool)",

    # Appearance / clothes
    "_mas_monika_clothes":              "Monika's current outfit",
    "_mas_monika_hair":                 "Monika's current hair",
    "_mas_likes_hairdown":              "Monika likes hair down (bool)",

    # Gameplay
    "_mas_current_background":          "Current background",
    "_mas_current_season":              "Current season (int: 1=spring,2=summer,3=fall,4=winter)",
    "_mas_xp_lvl":                      "XP level",
    "_mas_xp_tnl":                      "XP to next level",
    "_mas_islands_progress":            "Islands progress",
    "version_number":                   "MAS version",

    # Player preferences (NoneType = not yet asked)
    "_mas_pm_has_code_experience":      "Has coding experience",
    "_mas_pm_religious":                "Is religious",
    "_mas_pm_drinks_soda":              "Drinks soda",
    "_mas_pm_works_out":                "Works out",
    "_mas_pm_likes_poetry":             "Likes poetry",
    "_mas_pm_likes_rain":               "Likes rain",
    "_mas_pm_likes_horror":             "Likes horror",
    "_mas_pm_has_friends":              "Has friends",
    "_mas_pm_feels_lonely_sometimes":   "Feels lonely sometimes",
    "_mas_pm_see_therapist":            "Sees a therapist",
}

# ── Preset test scenarios ─────────────────────────────────────────────────────
PRESETS = {
    "fresh_start": {
        "description": "Brand new relationship, no history",
        "values": {
            "_mas_monika_lovecounter":  0,
            "_mas_first_kiss":          None,
            "_mas_last_kiss":           None,
            "_mas_just_friends":        False,
            "_mas_d25_spent_d25":       False,
            "_mas_f14_spent_f14":       False,
            "_mas_nye_spent_nye":       False,
        }
    },
    "long_term": {
        "description": "Long-term relationship, many milestones reached",
        "values": {
            "_mas_monika"
            "_mas_monika_lovecounter":      50,
            "_mas_monika_lovecountertime":  (datetime.datetime.now() - datetime.timedelta(days=365)).isoformat(),
            "_mas_first_kiss":              (datetime.datetime.now() - datetime.timedelta(days=300)).isoformat(),
            "_mas_last_kiss":               (datetime.datetime.now() - datetime.timedelta(days=1)).isoformat(),
            "_mas_d25_spent_d25":           True,
            "_mas_f14_spent_f14":           True,
            "_mas_nye_spent_nye":           True,
            "_mas_bday_said_happybday":     True,
            "_mas_just_friends":            False,
        }
    },
    "just_friends": {
        "description": "Friends-only mode, no romantic progression",
        "values": {
            "_mas_just_friends":            True,
            "_mas_first_kiss":              None,
            "_mas_last_kiss":               None,
            "_mas_monika_lovecounter":      0,
        }
    },
    "player_info_sample": {
        "description": "Fills in sample player appearance/personality info",
        "values": {
            "playername":                   "Michael",
            "gender":                       "M",
            "_mas_pm_eye_color":            "brown",
            "_mas_pm_hair_color":           "dark",
            "_mas_pm_hair_length":          "short",
            "_mas_pm_social_personality":   "introvert",
            "_mas_pm_has_code_experience":  True,
            "_mas_pm_likes_rain":           True,
            "_mas_pm_feels_lonely_sometimes": False,
            "_mas_pm_works_out":            False,
        }
    },
}


# ── Affection encoding ───────────────────────────────────────────────────────

# 7 big-endian doubles: affection, bank, cap_used, bypass_cap, freeze_ts,
# withdraw_ts, daily_cap  (mirrors _STRUCT_FMT in mas_affection.py)
_AFF_STRUCT = struct.Struct("!d d d d d d d")


def _to_struct(*args) -> bytes:
    return _AFF_STRUCT.pack(*args)


def _hexlify(bytes_: bytes) -> bytes:
    return binascii.hexlify(bytes_)


def _intob64(bytes_: bytes) -> bytes:
    return base64.b64encode(bytes_)


def encode_affection(*data) -> bytes:
    """
    Encode affection data into the MAS wire format.

    Packs 7 floats into a struct, hexlifies, then base64-encodes —
    producing a value suitable for _mas_affection_data in the persistent file.

    IN:
        *data - 7 float affection values (positional):
            [0] affection value
            [1] bypass overflow bank
            [2] daily non-bypass cap used
            [3] daily bypass cap used
            [4] freeze timestamp (last day-reset)
            [5] bank withdrawal timestamp
            [6] randomised daily cap

    OUT:
        bytes - encoded affection data
        None  - if an error occurred
    """
    try:
        encoded = _intob64(_hexlify(_to_struct(*data)))

    except (binascii.Incomplete, binascii.Error) as e:
        print(f"[error] Failed to convert hex data: {e}")

    except struct.error as e:
        print(f"[error] Failed to pack struct data: {e}")

    except Exception as e:
        print(f"[error] Failed to encode affection data: {e}")

    else:
        return encoded

    return None


# ── Persistent file I/O ───────────────────────────────────────────────────────

def find_persistent(custom_path: str = None) -> Path:
    """Locate the MAS persistent file."""
    if custom_path:
        p = Path(custom_path)
        if p.exists():
            return p
        raise FileNotFoundError(f"Persistent file not found at: {custom_path}")

    for path in SEARCH_PATHS:
        if path.exists():
            return path

    raise FileNotFoundError(
        "Could not find MAS persistent file automatically.\n"
        "Pass --persistent /path/to/persistent to specify its location."
    )


def load_persistent(path: Path) -> dict:
    """Load the Ren'Py persistent file via pickle."""
    with open(path, "rb") as f:
        data = f.read()

    # Ren'Py prepends a small header before the pickle payload
    # Try raw pickle first, then skip header bytes if that fails
    for skip in (0, 4, 8, 16):
        try:
            obj = pickle.loads(data[skip:])
            if isinstance(obj, dict):
                return obj
            # Some versions store as __dict__ of a Persistent object
            if hasattr(obj, "__dict__"):
                return obj.__dict__
        except Exception:
            continue

    raise ValueError("Unable to parse persistent file — format not recognised.")


def save_persistent(path: Path, data: dict, backup: bool = True):
    """Write modified persistent data back to disk."""
    if backup:
        bak = path.with_suffix(".bak")
        import shutil
        shutil.copy2(path, bak)
        print(f"  [backup] Saved original to {bak}")

    with open(path, "wb") as f:
        pickle.dump(data, f, protocol=2)  # Ren'Py uses protocol 2
    print(f"  [saved]  Written to {path}")


# ── Display helpers ───────────────────────────────────────────────────────────

def fmt_value(v) -> str:
    """Pretty-print a persistent value."""
    if v is None:
        return "None"
    if isinstance(v, datetime.datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, datetime.date):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, datetime.timedelta):
        return str(v)
    if isinstance(v, (dict, list, set)) and len(str(v)) > 80:
        return str(v)[:80] + "…"
    return repr(v)


def dump_tracked(data: dict):
    """Print all tracked keys and their current values."""
    print("\n{'='*60}")
    print("  MAS Persistent — Tracked Key Values")
    print("{'='*60}\n")
    col = max(len(k) for k in TRACKED_KEYS) + 2
    for key, desc in TRACKED_KEYS.items():
        val = data.get(key, "<NOT FOUND>")
        print(f"  {key:<{col}} {fmt_value(val)}")
        print(f"  {'':>{col}} # {desc}\n")


def dump_json(data: dict, path: str = None):
    """Export tracked keys to a JSON-serialisable dict."""
    out = {}
    for key in TRACKED_KEYS:
        v = data.get(key)
        if isinstance(v, (datetime.datetime, datetime.date)):
            out[key] = v.isoformat()
        elif isinstance(v, datetime.timedelta):
            out[key] = str(v)
        elif isinstance(v, set):
            out[key] = list(v)
        else:
            try:
                json.dumps(v)  # test serialisability
                out[key] = v
            except (TypeError, ValueError):
                out[key] = str(v)

    text = json.dumps(out, indent=2)
    if path:
        Path(path).write_text(text)
        print(f"Exported to {path}")
    else:
        print(text)
    return out


# ── Value coercion ────────────────────────────────────────────────────────────

def coerce_value(raw: str, existing):
    """
    Try to cast a raw string CLI value to the same type as the existing value.
    Supports: None, bool, int, float, datetime, date, str.
    """
    if raw.lower() in ("none", "null"):
        return None
    if raw.lower() in ("true", "yes", "1"):
        return True
    if raw.lower() in ("false", "no", "0"):
        return False

    # Try matching existing type
    if isinstance(existing, int):
        return int(raw)
    if isinstance(existing, float):
        return float(raw)
    if isinstance(existing, datetime.datetime):
        return datetime.datetime.fromisoformat(raw)
    if isinstance(existing, datetime.date):
        return datetime.date.fromisoformat(raw)

    # Fallback: try int → float → str
    for cast in (int, float):
        try:
            return cast(raw)
        except ValueError:
            pass
    return raw


# ── CLI actions ───────────────────────────────────────────────────────────────

def action_dump(data: dict, args):
    if args.json:
        dump_json(data, args.output)
    else:
        dump_tracked(data)


def action_set(data: dict, args) -> bool:
    key = args.key
    raw = args.value

    existing = data.get(key)
    new_val = coerce_value(raw, existing)

    print(f"\n  Key   : {key}")
    print(f"  Old   : {fmt_value(existing)}")
    print(f"  New   : {fmt_value(new_val)}")

    confirm = input("\n  Apply change? [y/N] ").strip().lower()
    if confirm == "y":
        data[key] = new_val
        return True
    print("  Cancelled.")
    return False


def action_preset(data: dict, args) -> bool:
    name = args.preset
    if name not in PRESETS:
        print(f"Unknown preset '{name}'. Available: {', '.join(PRESETS)}")
        return False

    preset = PRESETS[name]
    print(f"\n  Preset : {name}")
    print(f"  Info   : {preset['description']}\n")
    for key, val in preset["values"].items():
        old = data.get(key)
        print(f"    {key}")
        print(f"      {fmt_value(old)}  →  {fmt_value(val)}")

    confirm = input("\n  Apply this preset? [y/N] ").strip().lower()
    if confirm == "y":
        data.update(preset["values"])
        return True
    print("  Cancelled.")
    return False


def action_interactive(data: dict) -> bool:
    """Simple interactive menu."""
    changed = False
    while True:
        print("\n" + "="*50)
        print("  MAS Persistent Editor — Interactive Mode")
        print("="*50)
        print("  1. Show tracked key values")
        print("  2. Set a value manually")
        print("  3. Apply a preset scenario")
        print("  4. Export tracked keys to JSON")
        print("  5. Quit (discard changes)")
        print("  6. Save and quit")
        choice = input("\n  Choice: ").strip()

        if choice == "1":
            dump_tracked(data)

        elif choice == "2":
            print("\n  Available keys:")
            for i, (k, desc) in enumerate(TRACKED_KEYS.items(), 1):
                print(f"    {i:>3}. {k}  — {desc}")
            key_in = input("\n  Enter key name (or number): ").strip()
            keys = list(TRACKED_KEYS.keys())
            if key_in.isdigit():
                idx = int(key_in) - 1
                if 0 <= idx < len(keys):
                    key_in = keys[idx]
                else:
                    print("  Invalid index.")
                    continue
            if key_in not in data and key_in not in TRACKED_KEYS:
                print(f"  Warning: '{key_in}' not found in persistent data.")
            raw = input(f"  New value for {key_in}: ").strip()

            class FakeArgs:
                key = key_in
                value = raw

            if action_set(data, FakeArgs()):
                changed = True

        elif choice == "3":
            print("\n  Available presets:")
            for name, p in PRESETS.items():
                print(f"    {name:25s}  {p['description']}")
            name = input("\n  Preset name: ").strip()

            class FakeArgs:
                preset = name

            if action_preset(data, FakeArgs()):
                changed = True

        elif choice == "4":
            path = input("  Output JSON file (blank = print to screen): ").strip() or None
            dump_json(data, path)

        elif choice == "5":
            if changed:
                confirm = input("  You have unsaved changes. Really quit? [y/N] ").strip().lower()
                if confirm != "y":
                    continue
            print("  Bye!")
            return False

        elif choice == "6":
            return changed

        else:
            print("  Unknown option.")


# ── Entry point ───────────────────────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(
        description="MAS Persistent File Editor — read/modify save data for testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode (recommended)
  python mas_persistent_editor.py

  # Dump tracked keys to stdout
  python mas_persistent_editor.py --dump

  # Dump to JSON file
  python mas_persistent_editor.py --dump --json --output keys.json

  # Set a single key
  python mas_persistent_editor.py --set _mas_monika_lovecounter 25

  # Set player name
  python mas_persistent_editor.py --set playername Michael

  # Apply a preset
  python mas_persistent_editor.py --preset long_term

  # Specify persistent file location explicitly
  python mas_persistent_editor.py --persistent ~/MAS/game/saves/persistent --dump

Available presets:
""" + "\n".join(f"  {k:25s} {v['description']}" for k, v in PRESETS.items())
    )
    p.add_argument("--persistent", metavar="PATH",
                   help="Path to MAS persistent file (auto-detected if omitted)")
    p.add_argument("--no-backup", action="store_true",
                   help="Skip creating a .bak backup before writing")

    sub = p.add_subparsers(dest="action")

    # dump
    d = sub.add_parser("--dump", help="Print tracked key values")
    d.add_argument("--json", action="store_true", help="Output as JSON")
    d.add_argument("--output", metavar="FILE", help="Write JSON to file")

    # set
    s = sub.add_parser("--set", help="Set a single key to a value")
    s.add_argument("key", help="Key name")
    s.add_argument("value", help="New value (use 'None', 'True', 'False', ISO dates, or numbers)")

    # preset
    pr = sub.add_parser("--preset", help="Apply a preset test scenario")
    pr.add_argument("preset", choices=list(PRESETS.keys()))

    return p


def main():
    # Handle the common case where users pass --dump/--set/--preset as top-level args
    # (argparse subparsers need them without the --)
    argv = sys.argv[1:]
    for flag in ("--dump", "--set", "--preset"):
        if flag in argv:
            argv[argv.index(flag)] = flag.lstrip("-")

    parser = build_parser()
    args = parser.parse_args(argv)

    # Locate persistent file
    try:
        persistent_path = find_persistent(args.persistent if hasattr(args, "persistent") else None)
        print(f"[*] Using persistent file: {persistent_path}")
    except FileNotFoundError as e:
        print(f"[!] {e}")
        sys.exit(1)

    # Load data
    try:
        data = load_persistent(persistent_path)
        print(f"[*] Loaded {len(data)} keys.")
    except Exception as e:
        print(f"[!] Failed to load persistent file: {e}")
        sys.exit(1)

    # Dispatch action
    save_needed = False
    action = getattr(args, "action", None)

    if action == "dump":
        action_dump(data, args)
    elif action == "set":
        save_needed = action_set(data, args)
    elif action == "preset":
        save_needed = action_preset(data, args)
    else:
        # Default: interactive
        save_needed = action_interactive(data)

    # Save if modified
    if save_needed:
        no_backup = getattr(args, "no_backup", False)
        save_persistent(persistent_path, data, backup=not no_backup)
        print("[*] Done.")


if __name__ == "__main__":
    main()
