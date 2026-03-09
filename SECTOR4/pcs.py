#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║  PCS — Proximity Control String                              ║
║  Phoenix-DevOps-oS  //  SECTOR4                             ║
║                                                              ║
║  BLAKE2s truncated (8 bytes = 16 hex) — zero deps, max speed ║
║                                                              ║
║  Format: {hash16}:{zipcode}:{p1}:{p2}:{p3}:{definitive}     ║
║  Example: a1b2c3d4e5f6a7b8:red:72:85:94:0                  ║
║                                                              ║
║  Lifecycle:                                                  ║
║    Call 1 — stage set, PCS born                             ║
║    Call 2 — flock accumulates, probability climbs            ║
║    Call 3 — definitive hit, snap-clone fires                ║
╚══════════════════════════════════════════════════════════════╝
"""

import hashlib
import time
import os

# ── Clonepool zones (zipcode map) ────────────────────────────
ZONES = {
    "red":     {"tier": 1, "path": "/mnt/clonepool/@red"},
    "green":   {"tier": 1, "path": "/mnt/clonepool/@green"},
    "blue":    {"tier": 1, "path": "/mnt/clonepool/@blue"},
    "cyan":    {"tier": 2, "path": "/mnt/clonepool/@cyan"},
    "magenta": {"tier": 2, "path": "/mnt/clonepool/@magenta"},
    "yellow":  {"tier": 2, "path": "/mnt/clonepool/@yellow"},
}

# ── Definitive threshold ──────────────────────────────────────
DEFINITIVE_THRESHOLD = 90   # p3 must reach 90 to be definitive
SLOT_COUNTS = {z: 0 for z in ZONES}  # track slot usage per zone


# ── Hash ─────────────────────────────────────────────────────

def pcs_hash(data: bytes) -> str:
    """BLAKE2s truncated to 8 bytes = 16 hex chars. Fastest built-in."""
    return hashlib.blake2s(data, digest_size=8).hexdigest()


# ── Zone assignment ───────────────────────────────────────────

def assign_zone(family: str) -> str:
    """
    DB hands out the zipcode based on data family.
    Family maps to zone — birds of a feather land in the same zone.
    Falls back to least-loaded zone if family unknown.
    """
    family_map = {
        "physics":  "red",
        "ai":       "blue",
        "network":  "green",
        "assets":   "cyan",
        "system":   "magenta",
        "user":     "yellow",
    }
    zone = family_map.get(family)
    if zone:
        return zone
    # least loaded fallback
    return min(SLOT_COUNTS, key=SLOT_COUNTS.get)


# ── PCS ──────────────────────────────────────────────────────

class PCS:
    """
    Proximity Control String.
    Born at first input intercept. Carries its own destination.
    Probability chain builds until definitive — then snap-clone fires.
    """

    __slots__ = (
        "hash", "zipcode", "zone_path",
        "p1", "p2", "p3",
        "definitive", "created_at",
        "family", "call_count",
        "_raw",
    )

    def __init__(self, data: bytes, family: str = "system"):
        self.created_at  = time.monotonic_ns()
        self.family      = family
        self.call_count  = 0

        # Hash — 16 hex chars, fast
        self.hash        = pcs_hash(data + self.created_at.to_bytes(8, "little"))

        # Zipcode — DB-assigned address, travels with PCS forever
        self.zipcode     = assign_zone(family)
        self.zone_path   = ZONES[self.zipcode]["path"]

        # Probability chain — integer 0-100
        self.p1          = 0
        self.p2          = 0
        self.p3          = 0
        self.definitive  = False

        self._raw        = None  # cached string

    # ── Calls ─────────────────────────────────────────────────

    def call1(self) -> "PCS":
        """Stage set. Freewheeling pre-positions. PCS is live."""
        self.call_count = 1
        self.p1 = self._probability(self.hash, 1)
        self._raw = None
        return self

    def call2(self, new_data: bytes) -> "PCS":
        """Flock accumulates. Hash absorbs new data. Probability climbs."""
        self.call_count = 2
        combined        = self.hash.encode() + new_data
        self.hash       = pcs_hash(combined)
        self.p2         = self._probability(self.hash, 2)
        self._raw       = None
        return self

    def call3(self, new_data: bytes) -> "PCS":
        """Final accumulation. Definitive check. Snap-clone if threshold met."""
        self.call_count = 3
        combined        = self.hash.encode() + new_data
        self.hash       = pcs_hash(combined)
        self.p3         = self._probability(self.hash, 3)
        self.definitive = self.p3 >= DEFINITIVE_THRESHOLD
        self._raw       = None
        return self

    # ── Probability ───────────────────────────────────────────

    def _probability(self, h: str, call: int) -> int:
        """
        Derive probability from hash — deterministic, zero overhead.
        Takes two hex chars from call-offset position, converts to 0-100.
        """
        offset   = (call - 1) * 2
        raw      = int(h[offset:offset + 2], 16)   # 0-255
        return int(raw * 100 / 255)

    # ── String ────────────────────────────────────────────────

    def __str__(self) -> str:
        if self._raw is None:
            self._raw = (
                f"{self.hash}:{self.zipcode}:"
                f"{self.p1}:{self.p2}:{self.p3}:"
                f"{'1' if self.definitive else '0'}"
            )
        return self._raw

    def __repr__(self) -> str:
        return f"PCS({self})"

    # ── Parse ─────────────────────────────────────────────────

    @classmethod
    def from_string(cls, s: str) -> "PCS":
        """Reconstruct PCS from string. Fast split, no regex."""
        h, z, p1, p2, p3, d = s.split(":")
        obj            = object.__new__(cls)
        obj.hash       = h
        obj.zipcode    = z
        obj.zone_path  = ZONES.get(z, {}).get("path", "")
        obj.p1         = int(p1)
        obj.p2         = int(p2)
        obj.p3         = int(p3)
        obj.definitive = d == "1"
        obj.family     = "unknown"
        obj.call_count = 3 if obj.p3 > 0 else (2 if obj.p2 > 0 else 1)
        obj.created_at = 0
        obj._raw       = s
        return obj


# ── Snap-clone ────────────────────────────────────────────────

def snap_clone(pcs: PCS, src_path: str) -> bool:
    """
    Fires when definitive outcome is reached.
    btrfs snapshot to the PCS zipcode zone.
    Returns True on success.
    """
    if not pcs.definitive:
        return False

    zone_path = pcs.zone_path
    slot      = f"{zone_path}/{pcs.hash}"

    try:
        os.makedirs(zone_path, exist_ok=True)
        ret = os.system(
            f"btrfs subvolume snapshot '{src_path}' '{slot}' 2>/dev/null"
        )
        if ret != 0:
            # fallback: plain copy if not a btrfs subvolume
            os.system(f"cp -a '{src_path}' '{slot}' 2>/dev/null")
        return True
    except Exception:
        return False


# ── Quick test ────────────────────────────────────────────────

if __name__ == "__main__":
    print("PCS Engine — Phoenix-DevOps-oS\n")

    # Simulate incoming ball
    input_data = b"physics:collision:object_42"

    pcs = PCS(input_data, family="physics")

    pcs.call1()
    print(f"Call 1  →  {pcs}")

    pcs.call2(b"velocity:3.2:direction:northeast")
    print(f"Call 2  →  {pcs}")

    pcs.call3(b"outcome:confirmed:slot:7")
    print(f"Call 3  →  {pcs}")

    print(f"\nDefinitive : {pcs.definitive}")
    print(f"Zipcode    : {pcs.zipcode}  ({pcs.zone_path})")
    print(f"Hash len   : {len(pcs.hash)} chars  (vs SHA-256: 64)")

    # Parse round-trip
    s   = str(pcs)
    pcs2 = PCS.from_string(s)
    print(f"\nParse OK   : {str(pcs2) == s}")
