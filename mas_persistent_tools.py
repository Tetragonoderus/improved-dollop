"""
MAS Persistent File Tools
Utilities for reading and exploring a Monika After Story persistent file.
"""

import sys
import pickle
import datetime
import csv
from types import ModuleType
from pprint import pprint


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

            mod = ModuleType(fullname)
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


# ---------------------------------------------------------------------------
# Core loader
# ---------------------------------------------------------------------------

def load_persistent(path: str):
    """
    Load a MAS persistent file and return the deserialized object.
    Handles zlib-compressed files automatically.

    Args:
        path: Path to the persistent file.

    Returns:
        The persistent object (attributes accessible via .__dict__).
    """
    import zlib
    with open(path, "rb") as f:
        data = f.read()
    try:
        return pickle.loads(zlib.decompress(data), encoding='latin-1')
    except zlib.error:
        # Fall back to uncompressed in case an older version is used
        return pickle.loads(data, encoding='latin-1')


# ---------------------------------------------------------------------------
# Tool 1 - dump_keys
# ---------------------------------------------------------------------------

def dump_keys(persistent, prefix: str = "", sort: bool = True):
    """
    Print all keys in the persistent file, optionally filtered by prefix.

    Args:
        persistent: Loaded persistent object.
        prefix:     Only show keys starting with this string (e.g. "_mas_").
        sort:       Sort keys alphabetically (default True).
    """
    keys = persistent.__dict__.keys()
    if prefix:
        keys = [k for k in keys if k.startswith(prefix)]
    if sort:
        keys = sorted(keys)

    print(f"{'KEY':<60} TYPE")
    print("-" * 80)
    for key in keys:
        val = persistent.__dict__[key]
        print(f"{key:<60} {type(val).__name__}")
    print(f"\n{len(keys)} key(s) found.")


# ---------------------------------------------------------------------------
# Tool 2 - get_value
# ---------------------------------------------------------------------------

def get_value(persistent, key: str, pretty: bool = True):
    """
    Print the value of a specific persistent key.

    Args:
        persistent: Loaded persistent object.
        key:        The key to look up.
        pretty:     Use pprint for dicts/lists (default True).
    """
    if key not in persistent.__dict__:
        print(f"Key '{key}' not found.")
        return None

    val = persistent.__dict__[key]
    print(f"{key} ({type(val).__name__}):")
    if pretty and isinstance(val, (dict, list, set, tuple)):
        pprint(val)
    else:
        print(repr(val))
    return val


# ---------------------------------------------------------------------------
# Tool 3 - dump_affection
# ---------------------------------------------------------------------------

def dump_affection(persistent):
    """
    Print a summary of all affection-related fields.

    Args:
        persistent: Loaded persistent object.
    """
    AFF_KEYS = [
        "_mas_affection",
        "_mas_affection_daily",
        "_mas_affection_events_seen",
        "_mas_monika_tier",
        "_mas_monika_love",
        "_mas_monika_isdead",
        "_mas_monika_isgone",
        "_mas_monika_kill",
    ]

    print("=== Affection Summary ===")
    found_any = False
    for key in AFF_KEYS:
        if key in persistent.__dict__:
            found_any = True
            val = persistent.__dict__[key]
            print(f"  {key:<40} = {repr(val)}")

    # also grab anything with "aff" in the name not already listed
    extras = [
        k for k in sorted(persistent.__dict__.keys())
        if "aff" in k.lower() and k not in AFF_KEYS
    ]
    if extras:
        print("\n  -- other affection-related keys --")
        for key in extras:
            print(f"  {key:<40} = {repr(persistent.__dict__[key])}")

    if not found_any and not extras:
        print("  No affection keys found.")


# ---------------------------------------------------------------------------
# Tool 4 - dump_session
# ---------------------------------------------------------------------------

def dump_session(persistent):
    """
    Print a summary of session/timing-related fields.

    Args:
        persistent: Loaded persistent object.
    """
    SESSION_KEYS = [
        "_mas_last_session",
        "_mas_first_session",
        "_mas_sessionlength",
        "_mas_player_bday",
        "_mas_monika_bday",
        "_mas_last_update",
    ]

    print("=== Session Summary ===")
    for key in SESSION_KEYS:
        if key in persistent.__dict__:
            val = persistent.__dict__[key]
            print(f"  {key}:")
            if isinstance(val, dict):
                for k, v in val.items():
                    print(f"    {k}: {repr(v)}")
            else:
                print(f"    {repr(val)}")

    # anything with "session" or "last" or "first" not already listed
    extras = [
        k for k in sorted(persistent.__dict__.keys())
        if any(tok in k.lower() for tok in ("session", "last_", "first_"))
        and k not in SESSION_KEYS
    ]
    if extras:
        print("\n  -- other session-related keys --")
        for key in extras:
            print(f"  {key:<40} = {repr(persistent.__dict__[key])}")


# ---------------------------------------------------------------------------
# Tool 5 - dump_event_db
# ---------------------------------------------------------------------------

# Maps tuple index to field name (from dev_db.rpy)
_EV_FIELDS = [
    "eventlabel", "prompt", "label", "category",
    "unlocked", "random", "pool", "conditional",
    "action", "start_date", "end_date", "unlock_date",
    "shown_count", "diary_entry", "rules", "last_seen",
    "years", "sensitive", "aff_range",
]

def dump_event_db(persistent, db_key: str = "_mas_monika_topic_database",
                  filter_fn=None, limit: int = 20):
    """
    Print entries from an event database stored in persistent.

    Args:
        persistent: Loaded persistent object.
        db_key:     The persistent key holding the event dict.
        filter_fn:  Optional callable(label, ev_dict) -> bool to filter entries.
                    ev_dict keys match _EV_FIELDS names.
        limit:      Max entries to print (default 20, None for all).
    """
    if db_key not in persistent.__dict__:
        print(f"Key '{db_key}' not found in persistent.")
        return

    db = persistent.__dict__[db_key]
    if not isinstance(db, dict):
        print(f"'{db_key}' is not a dict (got {type(db).__name__}).")
        return

    print(f"=== Event DB: {db_key} ({len(db)} events) ===\n")

    printed = 0
    for label, ev_tuple in sorted(db.items()):
        # Convert tuple to dict for easier filtering/display
        if isinstance(ev_tuple, (list, tuple)):
            ev = {_EV_FIELDS[i]: ev_tuple[i] for i in range(min(len(ev_tuple), len(_EV_FIELDS)))}
        else:
            ev = {"raw": ev_tuple}

        if filter_fn and not filter_fn(label, ev):
            continue

        print(f"  [{label}]")
        for field, val in ev.items():
            if val is not None:
                print(f"    {field:<15} = {repr(val)}")
        print()

        printed += 1
        if limit and printed >= limit:
            remaining = len(db) - printed
            print(f"  ... (stopped at {limit}; {remaining} more entries not shown)")
            break


# ---------------------------------------------------------------------------
# Tool 6 - search
# ---------------------------------------------------------------------------

def search(persistent, query: str, case_sensitive: bool = False):
    """
    Search all persistent keys and string values for a substring.

    Args:
        persistent:      Loaded persistent object.
        query:           String to search for.
        case_sensitive:  Default False.
    """
    q = query if case_sensitive else query.lower()

    print(f"=== Search: '{query}' ===\n")
    matches = 0

    for key, val in sorted(persistent.__dict__.items()):
        key_hit = q in (key if case_sensitive else key.lower())
        val_str = repr(val)
        val_hit = q in (val_str if case_sensitive else val_str.lower())

        if key_hit or val_hit:
            matches += 1
            tag = "[KEY+VAL]" if (key_hit and val_hit) else ("[KEY]" if key_hit else "[VAL]")
            print(f"  {tag} {key} ({type(val).__name__})")
            # For short values, show inline
            if len(val_str) < 120:
                print(f"         = {val_str}")
            else:
                print(f"         = {val_str[:120]}...")
            print()

    print(f"{matches} match(es) found.")

#----------------------------------------------------------------------------
# Dump to CSV
#----------------------------------------------------------------------------

def dump_keys_to_csv(persistent, filename: str = "keys_dump.csv", prefix: str = "", sort: bool = True):
    """
    Exports keys and their types to a CSV file for spreadsheet inspection.
    """
    # Extract and filter keys
    keys = persistent.__dict__.keys()
    if prefix:
        keys = [k for k in keys if k.startswith(prefix)]
    if sort:
        keys = sorted(keys)

    # Write to CSV
    with open(filename, mode='w', newline='', encoding='utf-8') as csv_file:
        writer = csv.writer(csv_file)
        
        # Write the header row
        writer.writerow(["Key Name", "Data Type", "Value"])
        
        # Write the data rows
        for key in keys:
            val = persistent.__dict__[key]
            writer.writerow([key, type(val).__name__, val])

    print(f"Success! Exported {len(keys)} keys to {filename}")


# ---------------------------------------------------------------------------
# Example usage (run this file directly to test)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "persistent"

    print(f"Loading: {path}\n")
    p = load_persistent(path)

    print("1. All keys (prefix '_mas_aff'):")
    dump_keys(p, prefix="_mas_aff")

    print("\n2. Affection summary:")
    dump_affection(p)

    print("\n3. Session summary:")
    dump_session(p)

    print("\n4. First 5 events (unlocked only):")
    dump_event_db(p, filter_fn=lambda label, ev: ev.get("unlocked") is True, limit=5)

    print("\n5. Search for 'player':")
    search(p, "player")

    print(get_value(p, "playername"))
