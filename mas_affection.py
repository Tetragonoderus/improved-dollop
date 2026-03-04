"""
MAS Affection Manager
Replicates MAS's affection system for external use.

Usage:
    from mas_affection import MASAffectionManager
    mgr = MASAffectionManager("path/to/persistent")
    mgr.dump()
    mgr.gain_affection()
    mgr.save()

Or run directly for a read-only inspection:
    python mas_affection.py path/to/persistent
"""

import sys
import struct
import base64
import binascii
import random
import time
import datetime
import zlib
import pickle
from types import ModuleType
from copy import deepcopy


# ---------------------------------------------------------------------------
# Ren'Py stubs (same dynamic finder as mas_persistent_tools.py)
# ---------------------------------------------------------------------------

def _setup_renpy_stubs():
    if "renpy" in sys.modules:
        return

    class Persistent:
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
        def __setstate__(self, state):
            if isinstance(state, dict):
                self.__dict__.update(state)

    class _GenericStub:
        def __setstate__(self, state):
            if isinstance(state, dict):
                self.__dict__.update(state)

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
            for attr, val in _KNOWN_ATTRS.get(fullname, {}).items():
                setattr(mod, attr, val)
            def _getattr(name):
                cls = type(name, (_GenericStub,), {})
                setattr(mod, name, cls)
                return cls
            mod.__getattr__ = _getattr
            sys.modules[fullname] = mod
            parts = fullname.split(".")
            if len(parts) > 1:
                parent = sys.modules.get(".".join(parts[:-1]))
                if parent:
                    setattr(parent, parts[-1], mod)
            return mod

    sys.meta_path.insert(0, RenpyFinder())

_setup_renpy_stubs()


# ---------------------------------------------------------------------------
# Affection constants (from script-affection.rpy)
# ---------------------------------------------------------------------------

# Affection level IDs
BROKEN      = 1
DISTRESSED  = 2
UPSET       = 3
NORMAL      = 4
HAPPY       = 5
AFFECTIONATE = 6
ENAMORED    = 7
LOVE        = 8

_AFF_ORDER = [BROKEN, DISTRESSED, UPSET, NORMAL, HAPPY, AFFECTIONATE, ENAMORED, LOVE]

# Numeric thresholds for each level
_AFF_THRESHOLDS = [
    (BROKEN,       float("-inf"), -100),
    (DISTRESSED,   -100,          -75),
    (UPSET,        -75,           -30),
    (NORMAL,       -30,            30),
    (HAPPY,         30,           100),
    (AFFECTIONATE, 100,           400),
    (ENAMORED,     400,          1000),
    (LOVE,        1000,   float("inf")),
]

_AFF_NAMES = {
    BROKEN:       "BROKEN",
    DISTRESSED:   "DISTRESSED",
    UPSET:        "UPSET",
    NORMAL:       "NORMAL",
    HAPPY:        "HAPPY",
    AFFECTIONATE: "AFFECTIONATE",
    ENAMORED:     "ENAMORED",
    LOVE:         "LOVE",
}

# Default gain per level (from __DEF_AFF_GAIN_MAP)
_DEF_AFF_GAIN = {
    BROKEN:       0.25,
    DISTRESSED:   0.5,
    UPSET:        0.75,
    NORMAL:       1.0,
    HAPPY:        1.25,
    AFFECTIONATE: 1.5,
    ENAMORED:     2.5,
    LOVE:         2.0,
}

# Daily non-bypass cap: 9.0 (from _grant_aff: nonbypass_available = 9.0 - data[2])
_DAILY_CAP = 9.0

# Struct format: 7 big-endian doubles
_STRUCT_FMT = "!d d d d d d d"
_STRUCT = struct.Struct(_STRUCT_FMT)

# data indices
_IDX_AFF        = 0  # current affection value
_IDX_BANK       = 1  # bypass overflow bank
_IDX_CAP_USED   = 2  # today's non-bypass cap usage
_IDX_BYPASS_CAP = 3  # today's bypass cap usage
_IDX_FREEZE_TS  = 4  # timestamp of last day reset
_IDX_WITHDRAW_TS = 5 # timestamp of last bank withdrawal
_IDX_DAILY_CAP  = 6  # today's randomized daily cap


# ---------------------------------------------------------------------------
# Encode / decode (mirrors MAS's pipeline exactly)
# ---------------------------------------------------------------------------

def _encode(data: list) -> bytes:
    """list[7 floats] -> base64(hex(struct)) as bytes"""
    packed = _STRUCT.pack(*data)
    hexed  = binascii.hexlify(packed)
    return base64.b64encode(hexed)


def _decode(raw) -> list:
    """base64(hex(struct)) bytes/str -> list[7 floats]"""
    if isinstance(raw, str):
        raw = raw.encode("latin-1")
    return list(_STRUCT.unpack(binascii.unhexlify(base64.b64decode(raw))))


def _default_data() -> list:
    return [0.0] * 7


# ---------------------------------------------------------------------------
# Affection level helpers
# ---------------------------------------------------------------------------

def aff_level_from_value(value: float) -> int:
    """Return the affection level constant for a numeric value."""
    for level, low, high in _AFF_THRESHOLDS:
        if low <= value < high:
            return level
    return LOVE if value >= 1000 else BROKEN


def aff_level_name(level: int) -> str:
    return _AFF_NAMES.get(level, "UNKNOWN")


def default_gain_for_level(level: int) -> float:
    return _DEF_AFF_GAIN.get(level, 1.0)


# ---------------------------------------------------------------------------
# MASAffectionManager
# ---------------------------------------------------------------------------

class MASAffectionManager:
    """
    Reads and writes MAS affection data in a persistent file.

    Workflow:
        mgr = MASAffectionManager("path/to/persistent")
        mgr.dump()                  # inspect current state
        mgr.gain_affection()        # gain default amount for current level
        mgr.gain_affection(2.5)     # gain specific amount
        mgr.save()                  # write back to file
    """

    def __init__(self, path: str):
        self.path = path
        self.persistent = self._load_persistent()
        self._data = self._read_data()

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def _load_persistent(self):
        with open(self.path, "rb") as f:
            raw = f.read()
        try:
            return pickle.loads(zlib.decompress(raw), encoding="latin-1")
        except zlib.error:
            return pickle.loads(raw, encoding="latin-1")

    def _read_data(self) -> list:
        """Decode _mas_affection_data into a list of 7 floats."""
        raw = getattr(self.persistent, "_mas_affection_data", None)
        if raw is None:
            print("[warn] _mas_affection_data not found, using defaults.")
            return _default_data()
        try:
            return _decode(raw)
        except Exception as e:
            print(f"[warn] Failed to decode affection data: {e}. Using defaults.")
            return _default_data()

    def _write_data(self):
        """Encode current data list back into persistent and update backup."""
        encoded = _encode(self._data)
        self.persistent._mas_affection_data = encoded
        self._update_changed_timestamp("_mas_affection_data")
        self._push_backup(encoded)

    def save(self):
        """
        Write all changes back to the persistent file.
        Always backs up the file first.
        """
        import os, shutil

        # Write data into persistent object
        self._write_data()

        # Backup original
        backup_path = self.path + ".bak"
        shutil.copy2(self.path, backup_path)
        print(f"Backup written to: {backup_path}")

        # Re-serialize
        import io
        buf = io.BytesIO()
        pickle.dump(self.persistent, buf, protocol=2)
        compressed = zlib.compress(buf.getvalue())

        with open(self.path, "wb") as f:
            f.write(compressed)

        print(f"Saved: {self.path}")

    # ------------------------------------------------------------------
    # Backup management
    # ------------------------------------------------------------------

    def _push_backup(self, encoded_data):
        """
        Append a new backup entry to _mas_affection_backups.
        MAS checks that the last backup matches current data on load —
        if it doesn't match it restores from backup, undoing our changes.
        So we must push a fresh backup after every write.
        """
        backups = getattr(self.persistent, "_mas_affection_backups", None)
        if backups is None:
            return

        today = datetime.date.today()
        # Replace today's entry if one exists, otherwise append
        if backups and backups[-1][0] == today:
            backups[-1] = (today, encoded_data)
        else:
            backups.append((today, encoded_data))

        self._update_changed_timestamp("_mas_affection_backups")

    # ------------------------------------------------------------------
    # _changed timestamp management
    # ------------------------------------------------------------------

    def _update_changed_timestamp(self, key: str):
        """Update the _changed dict for a modified key."""
        changed = getattr(self.persistent, "_changed", None)
        if changed is not None:
            changed[key] = time.time()

    # ------------------------------------------------------------------
    # Core affection logic (mirrors _grant_aff from script-affection.rpy)
    # ------------------------------------------------------------------

    def gain_affection(
        self,
        amount: float = None,
        modifier: float = 1.0,
        bypass: bool = False,
    ) -> float:
        """
        Grant affection following MAS rules.

        Args:
            amount:   Amount to grant. None uses the default for the current level.
            modifier: Multiplier applied to amount.
            bypass:   If True, bypass the daily cap (up to 10 pts; 30 on special days).

        Returns:
            The actual amount of affection granted after caps/randomness.
        """
        data = self._data

        # Determine amount
        if amount is None:
            current_level = aff_level_from_value(data[_IDX_AFF])
            amount = default_gain_for_level(current_level)
        amount = float(amount) * modifier

        if amount <= 0.0:
            print("[error] gain_affection called with invalid amount.")
            return 0.0

        now_ = time.time()

        # Reset daily cap if it's a new day
        freeze_date = datetime.date.fromtimestamp(data[_IDX_FREEZE_TS]) if data[_IDX_FREEZE_TS] else None
        if freeze_date is None or freeze_date < datetime.date.today():
            data[_IDX_CAP_USED]   = 0.0
            data[_IDX_BYPASS_CAP] = 0.0
            data[_IDX_FREEZE_TS]  = now_
            data[_IDX_DAILY_CAP]  = random.triangular(5.0, 8.0)

        frozen = data[_IDX_CAP_USED] >= data[_IDX_DAILY_CAP]

        # Clamp amount (MAS caps individual grant at 50, then adds gauss noise)
        og_amount = amount
        amount = min(amount, 50.0)
        amount = max(0.0, random.gauss(amount, 0.25))

        # Clamp to max possible affection
        max_gain = max(1000000.0 - data[_IDX_AFF], 0.0)
        amount = min(amount, max_gain)

        bank_amount = 0.0

        if bypass:
            bypass_limit = 10.0  # 30.0 on special days — we use 10 conservatively
            bypass_available = max(bypass_limit - data[_IDX_BYPASS_CAP], 0.0)
            temp_amount = amount - bypass_available
            if temp_amount > 0.0:
                bank_available = max(70.0 - data[_IDX_BANK], 0.0)
                bank_amount = min(temp_amount, bank_available)
                amount -= temp_amount
        else:
            nonbypass_available = _DAILY_CAP - data[_IDX_CAP_USED]
            amount = min(amount, nonbypass_available)

        amount    = max(amount, 0.0)
        bank_amount = max(bank_amount, 0.0)

        if not frozen or bypass:
            data[_IDX_AFF]  += amount
            data[_IDX_BANK] += bank_amount

            if not bypass:
                data[_IDX_CAP_USED]   += amount
            else:
                data[_IDX_BYPASS_CAP] += amount

        self._data = data
        return amount

    # ------------------------------------------------------------------
    # Test / inspection tools
    # ------------------------------------------------------------------

    def get_affection(self) -> float:
        """Return the raw affection float value."""
        return self._data[_IDX_AFF]

    def get_level(self) -> int:
        """Return the current affection level constant."""
        return aff_level_from_value(self._data[_IDX_AFF])

    def get_level_name(self) -> str:
        """Return the current affection level as a human-readable string."""
        return aff_level_name(self.get_level())

    def get_cap_remaining(self) -> float:
        """Return how much non-bypass affection can still be gained today."""
        return max(_DAILY_CAP - self._data[_IDX_CAP_USED], 0.0)

    def dump(self):
        """Pretty-print all affection state."""
        d = self._data
        aff   = d[_IDX_AFF]
        level = aff_level_from_value(aff)

        print("=" * 50)
        print("  MAS Affection State")
        print("=" * 50)
        print(f"  Affection value   : {aff:.4f}")
        print(f"  Level             : {aff_level_name(level)} ({level})")
        print(f"  Bank              : {d[_IDX_BANK]:.4f}")
        print()
        print(f"  Daily cap         : {d[_IDX_DAILY_CAP]:.4f}")
        print(f"  Cap used (normal) : {d[_IDX_CAP_USED]:.4f}")
        print(f"  Cap remaining     : {self.get_cap_remaining():.4f}")
        print(f"  Cap used (bypass) : {d[_IDX_BYPASS_CAP]:.4f}")
        print()
        if d[_IDX_FREEZE_TS]:
            freeze_date = datetime.date.fromtimestamp(d[_IDX_FREEZE_TS])
            frozen = d[_IDX_CAP_USED] >= d[_IDX_DAILY_CAP]
            print(f"  Cap reset date    : {freeze_date}")
            print(f"  Frozen            : {frozen}")
        if d[_IDX_WITHDRAW_TS]:
            withdraw_date = datetime.date.fromtimestamp(d[_IDX_WITHDRAW_TS])
            print(f"  Last bank withdraw: {withdraw_date}")
        print()

        # Default gain for current level
        default_gain = default_gain_for_level(level)
        print(f"  Default gain/call : {default_gain}")
        print(f"  Next level        : {_next_level_info(aff)}")
        print("=" * 50)

        # Backup summary
        backups = getattr(self.persistent, "_mas_affection_backups", None)
        if backups:
            print(f"\n  Backups ({len(backups)} entries):")
            for i, (bdate, bdata) in enumerate(list(backups)[-3:], 1):
                try:
                    bval = _decode(bdata)[_IDX_AFF]
                    print(f"    [{i}] {bdate}  ->  {bval:.4f}")
                except Exception:
                    print(f"    [{i}] {bdate}  ->  (unreadable)")
            if len(backups) > 3:
                print(f"    ... ({len(backups) - 3} older entries not shown)")

    def simulate_gain(self, amount: float = None, modifier: float = 1.0,
                      bypass: bool = False, iterations: int = 10):
        """
        Simulate gain_affection N times without modifying state.
        Useful for seeing what a session would yield before committing.

        Args:
            amount:     Amount per call (None = default for current level).
            modifier:   Multiplier.
            bypass:     Use bypass logic.
            iterations: Number of calls to simulate.
        """
        # Work on a deep copy so we don't touch real state
        original_data = self._data
        self._data = deepcopy(original_data)

        total = 0.0
        print(f"\nSimulating {iterations} gain_affection calls "
              f"(amount={amount}, modifier={modifier}, bypass={bypass}):")
        print(f"  Starting affection: {self._data[_IDX_AFF]:.4f}")

        for i in range(iterations):
            gained = self.gain_affection(amount=amount, modifier=modifier, bypass=bypass)
            total += gained
            print(f"  [{i+1:2d}] gained {gained:.4f}  |  total {self._data[_IDX_AFF]:.4f}")

        print(f"\n  Total gained   : {total:.4f}")
        print(f"  Final value    : {self._data[_IDX_AFF]:.4f}")
        print(f"  Final level    : {self.get_level_name()}")
        print(f"  Cap remaining  : {self.get_cap_remaining():.4f}")

        # Restore
        self._data = original_data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_level_info(aff: float) -> str:
    """Return a string describing how far the next level is."""
    for level, low, high in _AFF_THRESHOLDS:
        if low <= aff < high:
            if high == float("inf"):
                return "already at max level (LOVE)"
            return f"{aff_level_name(_AFF_ORDER[_AFF_ORDER.index(level) + 1])} at {high:.0f} (need {high - aff:.2f} more)"
    return "unknown"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "persistent"

    print(f"Loading: {path}\n")
    mgr = MASAffectionManager(path)

    mgr.dump()

    print("\n--- Simulation (5 default gains, no bypass) ---")
    mgr.simulate_gain(iterations=5)

    print("\n--- Simulation (5 default gains, bypass) ---")
    mgr.simulate_gain(bypass=True, iterations=5)

    print("\nNo changes have been written. Call mgr.save() to commit.")
