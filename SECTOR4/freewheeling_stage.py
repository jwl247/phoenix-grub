#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║  Freewheeling Stage — Phoenix-DevOps-oS  //  SECTOR4        ║
║                                                              ║
║  Freewheeling IS the stage.                                  ║
║  Storage tied directly to him.                               ║
║  Birds of a feather flock together.                          ║
║                                                              ║
║  3-call lifecycle:                                           ║
║    Call 1 — stage pre-positioned, slot reserved              ║
║    Call 2 — flock accumulates in warm storage                ║
║    Call 3 — definitive → snap-clone fires → ring post-stage  ║
║                                                              ║
║  Flocks group by zipcode. Similar data lands together.       ║
║  systemd rings handle post-stage per zone.                   ║
╚══════════════════════════════════════════════════════════════╝
"""

import os
import time
import subprocess
from collections import defaultdict
from threading import Lock
from pcs import PCS, snap_clone, ZONES

# ── Ring → systemd service map ────────────────────────────────
# Each zone is owned by a coms ring. After snap-clone, that ring fires.
ZONE_RING = {
    "red":     "coms1",
    "green":   "coms2",
    "blue":    "coms3",
    "cyan":    "coms1",
    "magenta": "coms2",
    "yellow":  "coms3",
}

# ── Slot state ────────────────────────────────────────────────
SLOT_EMPTY    = 0
SLOT_STAGED   = 1   # call1 — pre-positioned
SLOT_WARM     = 2   # call2 — accumulating
SLOT_DEFINITIVE = 3 # call3 — ready to commit


class Slot:
    """One PCS lifecycle slot inside Freewheeling."""
    __slots__ = (
        "pcs", "state", "warm", "src_path", "created_at", "committed"
    )

    def __init__(self, pcs: PCS):
        self.pcs        = pcs
        self.state      = SLOT_EMPTY
        self.warm       = []        # accumulating data chunks
        self.src_path   = None      # source path for snap-clone
        self.created_at = time.monotonic_ns()
        self.committed  = False


class FreewheelStage:
    """
    The stage. Manages all active PCS slots.
    Flocks group by zipcode — birds of a feather land together.
    On definitive: fires snap_clone → triggers systemd ring post-stage.
    """

    def __init__(self, base_src: str = "/tmp/phoenix_stage"):
        self.base_src   = base_src
        self._slots: dict[str, Slot] = {}       # hash → Slot
        self._flocks: dict[str, list] = defaultdict(list)  # zipcode → [hashes]
        self._lock      = Lock()
        os.makedirs(base_src, exist_ok=True)

    # ── Call 1 — Stage set ────────────────────────────────────

    def call1(self, data: bytes, family: str = "system") -> PCS:
        """
        Intercept at earliest input.
        PCS born, stage pre-positioned, slot reserved.
        Freewheeling is ready before data arrives.
        """
        pcs = PCS(data, family=family)
        pcs.call1()

        slot          = Slot(pcs)
        slot.state    = SLOT_STAGED
        slot.src_path = os.path.join(self.base_src, pcs.hash)
        os.makedirs(slot.src_path, exist_ok=True)

        with self._lock:
            self._slots[pcs.hash]  = slot
            self._flocks[pcs.zipcode].append(pcs.hash)

        return pcs

    # ── Call 2 — Flock accumulates ────────────────────────────

    def call2(self, pcs_hash: str, data: bytes) -> PCS | None:
        """
        Birds of a feather accumulate.
        Data chunks join the flock in warm storage.
        Hash absorbs new data — probability climbs.
        """
        with self._lock:
            slot = self._slots.get(pcs_hash)
        if slot is None:
            return None

        slot.pcs.call2(data)
        slot.warm.append(data)
        slot.state = SLOT_WARM

        # Write chunk to stage dir — fast, no serialization
        chunk_path = os.path.join(slot.src_path, f"c2_{len(slot.warm)}")
        with open(chunk_path, "wb") as f:
            f.write(data)

        return slot.pcs

    # ── Call 3 — Definitive check, snap-clone ─────────────────

    def call3(self, pcs_hash: str, data: bytes) -> tuple[PCS, bool]:
        """
        Final accumulation. Definitive check.
        If definitive: snap-clone fires, ring handles post-stage.
        Returns (pcs, committed).
        """
        with self._lock:
            slot = self._slots.get(pcs_hash)
        if slot is None:
            return None, False

        slot.pcs.call3(data)
        slot.warm.append(data)

        # Write final chunk
        chunk_path = os.path.join(slot.src_path, f"c3_{len(slot.warm)}")
        with open(chunk_path, "wb") as f:
            f.write(data)

        if slot.pcs.definitive:
            slot.state     = SLOT_DEFINITIVE
            slot.committed = snap_clone(slot.pcs, slot.src_path)
            if slot.committed:
                self._post_stage(slot.pcs)
                self._release(pcs_hash)
        return slot.pcs, slot.committed

    # ── Post-stage — through captain → propcoms → ring ───────────

    def _post_stage(self, pcs: PCS) -> None:
        """
        Snap-clone committed.
        Signal goes to Cpt_conductor → propcoms validates → correct coms ring.
        Nothing talks to a ring directly — everything goes through propcoms.
        """
        ring = ZONE_RING.get(pcs.zipcode)
        if not ring:
            return

        # Ball for the captain — propcoms will validate target
        ball = {
            "type":    pcs.family,
            "pcs":     str(pcs),
            "zipcode": pcs.zipcode,
            "target":  ring,
            "hash":    pcs.hash,
            "stage":   "post",
        }

        # Signal captain — non-blocking, propcoms routes from here
        env = os.environ.copy()
        env["PHOENIX_PCS"]     = str(pcs)
        env["PHOENIX_ZONE"]    = pcs.zipcode
        env["PHOENIX_RING"]    = ring
        env["PHOENIX_BALL"]    = str(ball)

        # Captain receives, propcoms validates, ring handles post-stage
        subprocess.Popen(
            ["systemctl", "--no-block", "start", "phoenix-cpt@" + pcs.hash + ".service"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    # ── Release slot ──────────────────────────────────────────

    def _release(self, pcs_hash: str) -> None:
        """Free the slot after commit. Keep flock entry for audit."""
        slot = self._slots.pop(pcs_hash, None)
        if slot:
            # Clean stage dir — data is in clonepool now
            try:
                import shutil
                shutil.rmtree(slot.src_path, ignore_errors=True)
            except Exception:
                pass

    # ── Flock status ──────────────────────────────────────────

    def flock_status(self) -> dict:
        """Snapshot of all active flocks — what's in flight."""
        with self._lock:
            return {
                zone: {
                    "count":    len(hashes),
                    "slots": [
                        {
                            "hash":  h,
                            "state": self._slots[h].state,
                            "pcs":   str(self._slots[h].pcs),
                        }
                        for h in hashes if h in self._slots
                    ]
                }
                for zone, hashes in self._flocks.items()
                if hashes
            }

    def active_count(self) -> int:
        with self._lock:
            return len(self._slots)


# ── Quick test ────────────────────────────────────────────────

if __name__ == "__main__":
    print("Freewheeling Stage — Phoenix-DevOps-oS\n")

    stage = FreewheelStage()

    # Simulate 3 balls coming in
    balls = [
        (b"physics:collision:obj_1",  "physics"),
        (b"ai:inference:model_7",     "ai"),
        (b"network:packet:stream_3",  "network"),
    ]

    active = []
    for data, family in balls:
        pcs = stage.call1(data, family)
        print(f"Call 1  [{family:8s}]  {pcs}")
        active.append(pcs.hash)

    print()

    for h in active:
        pcs = stage.call2(h, b"accumulate:chunk:alpha")
        if pcs:
            print(f"Call 2  [{pcs.zipcode:8s}]  {pcs}")

    print()

    for h in active:
        pcs, committed = stage.call3(h, b"outcome:final:beta")
        if pcs:
            print(f"Call 3  [{pcs.zipcode:8s}]  {pcs}  definitive={pcs.definitive}  committed={committed}")

    print(f"\nActive slots remaining : {stage.active_count()}")
    print(f"Flock status           : {stage.flock_status()}")
