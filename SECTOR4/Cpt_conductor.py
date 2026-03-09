import time
from dataclasses import dataclass, field
from typing import Any, Dict, List
from enum import Enum
from collections import deque

class StorageLanguage(Enum):
    VECTOR = "vector"
    NOSQL = "nosql"
    RELATIONAL = "relational"
    TIMESERIES = "timeseries"

@dataclass
class QuadralingualPacket:
    """The Helix DNA of every signal inside the officer's box."""
    packet_id: str
    _raw_data: Any
    created_at: float = field(default_factory=time.time)

    def in_language(self, language: StorageLanguage) -> Any:
        """Universal translator for the 4 helix languages."""
        if language == StorageLanguage.VECTOR: return self._to_vector()
        if language == StorageLanguage.NOSQL: return self._to_nosql()
        if language == StorageLanguage.RELATIONAL: return self._to_relational()
        if language == StorageLanguage.TIMESERIES: return self._to_timeseries()

    def _to_vector(self) -> List[float]:
        if isinstance(self._raw_data, (list, tuple)):
            return [float(x) for x in self._raw_data if isinstance(x, (int, float))]
        return [float(hash(str(self._raw_data)) % 1000) / 1000]

    def _to_nosql(self) -> Dict[str, Any]:
        return {"id": self.packet_id, "data": self._raw_data, "type": type(self._raw_data).__name__}

    def _to_relational(self) -> Dict[str, Any]:
        return {"id": self.packet_id, "val": str(self._raw_data), "ts": self.created_at}

    def _to_timeseries(self) -> List[Dict[str, Any]]:
        return [{"timestamp": self.created_at, "metric": "signal", "value": str(self._raw_data)}]

class CommsOfficer:
    """
    A walking Helix station. 
    The 'Ring' is a circular buffer keeping data quadralingual.
    """
    def __init__(self, station_zip: str, ring_size: int = 16):
        self.station_zip = station_zip
        self.ring = deque(maxlen=ring_size) # The internal Helix Ring

    def receive_signal(self, channel: str, zipcode: str, data: Any):
        """Processes incoming data into the Helix Ring."""
        # 1. Zipcode Gate for PropComs
        if channel == "propcoms" and zipcode != self.station_zip:
            return # Silent drop for unknown zipcodes

        # 2. Quad Engine Processing (Convert to Helix Packet)
        packet = QuadralingualPacket(packet_id=f"SIG_{int(time.time()*1000)}", _raw_data=data)
        self.ring.append(packet)

        # 3. Upbeat Signal Acknowledgment
        if channel == "kernel":
            print(f"⚡ [KERNEL] Priority Signal stowed in Helix Ring.")
            print(f"   -> Relational View: {packet.in_language(StorageLanguage.RELATIONAL)}")
        else:
            print(f"🎵 [PROPCOMS] Zip {zipcode} called! Signal sync complete.")
            print(f"   -> NoSQL View: {packet.in_language(StorageLanguage.NOSQL)}")

# ============================================================================
# OPERATION: BEACH WALK SECTOR
# ============================================================================

# Officer stationed at Zip 80210
officer = CommsOfficer(station_zip="80210")

# Kernel bypasses zip checks
officer.receive_signal("kernel", "SYSTEM", "REBOOT_SPIRAL_PROTOCOL")

# PropComs: Zip 90210 is ignored
officer.receive_signal("propcoms", "90210", "Wait, I have data!")

# PropComs: Zip 80210 is accepted (Perfect for a beach walk!)
officer.receive_signal("propcoms", "80210", "Conditions: Sunny, Blue Skies.")
