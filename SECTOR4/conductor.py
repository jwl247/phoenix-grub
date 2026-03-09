#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║  Cpt_conductor — Phoenix-DevOps-oS  //  SECTOR4             ║
║                                                              ║
║  Captain talks to the kernel only.                           ║
║  Everything is ingress / egress. No loops.                   ║
║                                                              ║
║  Ingress: receives ball from Freewheeling post snap-clone    ║
║  Kernel:  selects slot (0-3), converts to QuadPacket         ║
║  Propcoms: zipcode validates, routes to correct ring         ║
║  Egress:  ring handles post-stage, done                      ║
║                                                              ║
║  Kernel slots (from D1 phoenix_db):                         ║
║    0  c_pure        — max speed, peak traffic   → VECTOR     ║
║    1  c_sideload    — balanced, extended calls  → NOSQL      ║
║    2  python_user   — flexible, moderate load   → RELATIONAL ║
║    3  python_full   — full flexibility, dev     → TIMESERIES ║
╚══════════════════════════════════════════════════════════════╝
"""

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from enum import Enum
from pcs import PCS
from helix_api import Propcoms

# ── Storage languages (Helix DNA) ────────────────────────────
class StorageLanguage(Enum):
    VECTOR      = "vector"
    NOSQL       = "nosql"
    RELATIONAL  = "relational"
    TIMESERIES  = "timeseries"

# ── Kernel slot definitions (mirrors D1 kernel_slots) ─────────
KERNEL_SLOTS = {
    0: {"type": "c_pure",      "layer": StorageLanguage.VECTOR,     "notes": "max speed, peak traffic"},
    1: {"type": "c_sideload",  "layer": StorageLanguage.NOSQL,      "notes": "balanced, extended calls"},
    2: {"type": "python_user", "layer": StorageLanguage.RELATIONAL,  "notes": "flexible, moderate load"},
    3: {"type": "python_full", "layer": StorageLanguage.TIMESERIES,  "notes": "full flexibility"},
}

# Family → preferred kernel slot
FAMILY_SLOT = {
    "physics":  0,   # c_pure — max speed
    "ai":       3,   # python_full — full flexibility
    "network":  1,   # c_sideload — balanced
    "assets":   1,   # c_sideload — balanced
    "system":   0,   # c_pure — max speed
    "user":     2,   # python_user — flexible
}


# ── Quadralingual Packet (Helix DNA) ──────────────────────────

@dataclass
class QuadPacket:
    """Every signal inside the captain is quadralingual."""
    packet_id:  str
    pcs:        str         # PCS string
    data:       Any
    slot:       int         # kernel slot used
    language:   StorageLanguage
    created_at: float = field(default_factory=time.time)

    def as_vector(self):
        return [float(int(self.pcs[i:i+2], 16)) for i in range(0, 16, 2)]

    def as_nosql(self) -> dict:
        return {"id": self.packet_id, "pcs": self.pcs, "data": str(self.data)}

    def as_relational(self) -> dict:
        return {"id": self.packet_id, "pcs": self.pcs, "ts": self.created_at, "val": str(self.data)}

    def as_timeseries(self) -> list:
        return [{"ts": self.created_at, "metric": "signal", "pcs": self.pcs, "val": str(self.data)}]

    def native(self) -> Any:
        """Return data in the packet's native language."""
        return {
            StorageLanguage.VECTOR:     self.as_vector,
            StorageLanguage.NOSQL:      self.as_nosql,
            StorageLanguage.RELATIONAL: self.as_relational,
            StorageLanguage.TIMESERIES: self.as_timeseries,
        }[self.language]()


# ── Kernel router — slot selection ────────────────────────────

class KernelRouter:
    """
    Selects kernel slot based on family and load.
    No loops — just picks a slot and hands the packet off.
    """
    __slots__ = ("_load",)

    def __init__(self):
        self._load = {0: 0, 1: 0, 2: 0, 3: 0}

    def select_slot(self, family: str) -> int:
        preferred = FAMILY_SLOT.get(family, 2)
        # If preferred slot overloaded (>100 in flight), step down
        if self._load[preferred] > 100:
            preferred = min(self._load, key=self._load.get)
        self._load[preferred] += 1
        return preferred

    def release_slot(self, slot: int) -> None:
        if self._load[slot] > 0:
            self._load[slot] -= 1

    def load_snapshot(self) -> dict:
        return dict(self._load)


# ── Propcoms gate ─────────────────────────────────────────────

class PropcGate:
    """
    Wraps Propcoms. Zipcode validates every packet before ring dispatch.
    Propcoms is one entity — symlinked. Same validator everywhere.
    """
    __slots__ = ("_prop",)

    def __init__(self):
        self._prop = Propcoms()

    # Ring name → propcoms system name
    _RING_MAP = {
        "coms1": "system_1",
        "coms2": "system_2",
        "coms3": "system_3",
        "coms4": "system_1",   # coms4 peers through system_1
    }

    def validate(self, packet: QuadPacket, target_ring: str) -> bool:
        """
        Returns True if packet is cleared for the target ring.
        Data stays quadralingual while in custody — language preserved on packet.
        """
        sys_target = self._RING_MAP.get(target_ring, "system_1")
        ball = {
            "type":     packet.language.value,   # quadralingual identity travels with ball
            "pcs":      packet.pcs,
            "target":   sys_target,
            "language": packet.language.value,   # custody chain — language never stripped
        }
        contextual = {"target": sys_target, "escalate": False}
        result = self._prop.validate(ball, contextual)
        return result.get("validated", False) and not result.get("escalate", False)

    def tick(self) -> dict:
        return self._prop.tick("captain", "kernel")

    def ring_alive(self) -> bool:
        return self._prop.ring_alive()


# ── Captain Conductor ─────────────────────────────────────────

class CptConductor:
    """
    Ingress → kernel → propcoms → egress. No loops.
    Captain talks to kernel only.
    Propcoms validates before any ring sees the packet.
    """

    def __init__(self, ring_size: int = 64):
        self._router    = KernelRouter()
        self._gate      = PropcGate()
        self._ring      = deque(maxlen=ring_size)   # in-flight packets
        self._egress    = deque(maxlen=ring_size)   # completed packets
        self._seq       = 0

    # ── Ingress ───────────────────────────────────────────────

    def ingress(self, pcs: PCS, data: Any) -> Optional[QuadPacket]:
        """
        Ball arrives from Freewheeling post snap-clone.
        Captain selects kernel slot, wraps in QuadPacket, sends to gate.
        """
        if not self._gate.ring_alive():
            return None

        slot     = self._router.select_slot(pcs.family)
        language = KERNEL_SLOTS[slot]["layer"]

        self._seq += 1
        packet = QuadPacket(
            packet_id  = f"CPT_{self._seq:06d}",
            pcs        = str(pcs),
            data       = data,
            slot       = slot,
            language   = language,
        )

        self._ring.append(packet)
        self._gate.tick()

        # Route through propcoms to correct ring
        target = f"coms{(slot % 4) + 1}"
        if self._gate.validate(packet, target):
            return self._dispatch(packet, target)

        # Propcoms escalated — try next available ring
        for fallback in ["coms1", "coms2", "coms3", "coms4"]:
            if fallback != target and self._gate.validate(packet, fallback):
                return self._dispatch(packet, fallback)

        return None

    # ── Dispatch → egress ─────────────────────────────────────

    def _dispatch(self, packet: QuadPacket, ring: str) -> QuadPacket:
        """
        Propcoms cleared it. Dispatch to ring. Move to egress.
        This is the exit — no return path.
        """
        self._router.release_slot(packet.slot)
        self._egress.append(packet)
        return packet

    # ── Status ────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "in_flight":    len(self._ring),
            "egress_count": len(self._egress),
            "kernel_load":  self._router.load_snapshot(),
            "ring_alive":   self._gate.ring_alive(),
            "seq":          self._seq,
        }


# ── Quick test ────────────────────────────────────────────────

if __name__ == "__main__":
    print("Cpt_conductor — Phoenix-DevOps-oS\n")

    cpt = CptConductor()

    # Simulate balls arriving from Freewheeling post snap-clone
    from freewheeling_stage import FreewheelStage
    stage = FreewheelStage()

    balls = [
        (b"physics:collision:obj_1",  "physics"),
        (b"ai:inference:model_7",     "ai"),
        (b"network:packet:stream_3",  "network"),
        (b"system:heartbeat:tick_1",  "system"),
    ]

    for data, family in balls:
        pcs       = stage.call1(data, family)
        orig_hash = pcs.hash                    # key never changes — original hash
        stage.call2(orig_hash, b"chunk:alpha")
        pcs, committed = stage.call3(orig_hash, b"outcome:final")

        packet = cpt.ingress(pcs, {"ball": data.decode(), "family": family})
        if packet:
            slot_info = KERNEL_SLOTS[packet.slot]
            print(f"  [{family:8s}]  slot={packet.slot} ({slot_info['type']:12s})  "
                  f"lang={packet.language.value:10s}  id={packet.packet_id}")
            print(f"             pcs={packet.pcs}")
            print(f"             native={packet.native()}")
            print()

    print(f"Status: {cpt.status()}")
