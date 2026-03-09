import json
import time
import math
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, Callable
from enum import Enum
from collections import defaultdict, deque
from threading import Lock
import sys

# ============================================================================
# MODULE 1: CORE DATA STRUCTURES
# ============================================================================

class StorageType(Enum):
    """Types of storage blocks in the helix"""
    VECTOR = 0
    NOSQL = 1
    RELATIONAL = 2
    TIME_SERIES = 3


class StorageLanguage(Enum):
    """The 4 languages data can be represented in"""
    VECTOR = "vector"
    NOSQL = "nosql"
    RELATIONAL = "relational"
    TIMESERIES = "timeseries"


@dataclass
class Point3D:
    """3D point in space"""
    x: float
    y: float
    z: float

    def distance_to(self, other: 'Point3D') -> float:
        """Calculate Euclidean distance to another point"""
        return math.sqrt(
            (self.x - other.x)**2 +
            (self.y - other.y)**2 +
            (self.z - other.z)**2
        )

    def __repr__(self):
        return f"Point3D({self.x:.2f}, {self.y:.2f}, {self.z:.2f})"


# ============================================================================
# MODULE 2: QUADRALINGUAL DATA PACKETS
# ============================================================================

@dataclass
class QuadralingualPacket:
    """
    Data packet that exists in all 4 languages simultaneously.
    Each format is a VIEW of the same data - no duplication.
    """
    packet_id: str
    created_at: float = field(default_factory=time.time)
    _raw_data: Any = None
    _vector_form: Optional[List[float]] = None
    _nosql_form: Optional[Dict[str, Any]] = None
    _relational_form: Optional[Dict[str, Any]] = None
    _timeseries_form: Optional[List[Dict[str, Any]]] = None

    @classmethod
    def from_data(cls, packet_id: str, data: Any) -> 'QuadralingualPacket':
        """Create packet from any input data"""
        packet = cls(packet_id=packet_id, _raw_data=data)
        packet._translate_to_all_languages()
        return packet

    def _translate_to_all_languages(self):
        """Convert raw data into all 4 language formats"""
        self._vector_form = self._to_vector()
        self._nosql_form = self._to_nosql()
        self._relational_form = self._to_relational()
        self._timeseries_form = self._to_timeseries()

    def _to_vector(self) -> List[float]:
        """VECTOR LANGUAGE: Everything becomes numbers"""
        if isinstance(self._raw_data, (list, tuple)):
            return [float(x) if isinstance(x, (int, float)) else 0.0
                    for x in self._raw_data]  # FIX: was ]:

        elif isinstance(self._raw_data, dict):
            values = []
            for key, value in sorted(self._raw_data.items()):
                if isinstance(value, (int, float)):
                    values.append(float(value))
                elif isinstance(value, str):
                    values.append(float(hash(value) % 1000) / 1000)
                elif isinstance(value, (list, tuple)):
                    values.extend([float(v) if isinstance(v, (int, float)) else 0.0
                                for v in value])  # FIX: was ):
            return values

        elif isinstance(self._raw_data, str):
            return [float(ord(c)) / 255.0 for c in self._raw_data[:128]]

        elif isinstance(self._raw_data, (int, float)):
            return [float(self._raw_data)]

        else:
            return [float(hash(str(self._raw_data)) % 1000) / 1000]

    def _to_nosql(self) -> Dict[str, Any]:
        """NOSQL LANGUAGE: Everything becomes nested documents"""
        base_doc = {
            "_id": self.packet_id,
            "_created": self.created_at,
            "_type": type(self._raw_data).__name__
        }

        if isinstance(self._raw_data, dict):
            base_doc["data"] = self._raw_data.copy()
        elif isinstance(self._raw_data, (list, tuple)):
            base_doc["data"] = {
                "items": list(self._raw_data),
                "length": len(self._raw_data)
            }
        elif isinstance(self._raw_data, str):
            base_doc["data"] = {
                "text": self._raw_data,
                "length": len(self._raw_data)
            }
        else:
            base_doc["data"] = {"value": self._raw_data}  # FIX: was missing body

        if self._vector_form:
            base_doc["_embedding"] = self._vector_form

        return base_doc

    def _to_relational(self) -> Dict[str, Any]:
        """RELATIONAL LANGUAGE: Everything becomes flat rows"""
        row = {
            "id": self.packet_id,
            "created_at": self.created_at,
            "data_type": type(self._raw_data).__name__
        }

        if isinstance(self._raw_data, dict):
            for key, value in self._raw_data.items():
                safe_key = str(key).replace(" ", "_").lower()
                if isinstance(value, (int, float, str, bool)):
                    row[f"col_{safe_key}"] = value
                else:
                    row[f"col_{safe_key}"] = str(value)

        elif isinstance(self._raw_data, (list, tuple)):
            for i, item in enumerate(self._raw_data[:10]):
                if isinstance(item, (int, float, str, bool)):
                    row[f"item_{i}"] = item

        elif isinstance(self._raw_data, str):
            row["text_value"] = self._raw_data
            row["text_length"] = len(self._raw_data)

        else:
            row["value"] = str(self._raw_data)

        if self._vector_form:
            magnitude = math.sqrt(sum(x*x for x in self._vector_form))
            row["vector_magnitude"] = magnitude
            row["vector_dimensions"] = len(self._vector_form)

        return row

    def _to_timeseries(self) -> List[Dict[str, Any]]:
        """TIMESERIES LANGUAGE: Everything becomes time-indexed points"""
        points = []

        if isinstance(self._raw_data, dict):
            for i, (key, value) in enumerate(self._raw_data.items()):
                points.append({
                    "timestamp": self.created_at + i * 0.001,
                    "metric": str(key),
                    "value": value if isinstance(value, (int, float)) else None,
                    "value_str": str(value) if not isinstance(value, (int, float)) else None,
                    "sequence": i
                })

        elif isinstance(self._raw_data, (list, tuple)):
            for i, item in enumerate(self._raw_data):
                points.append({
                    "timestamp": self.created_at + i * 0.001,
                    "metric": f"item_{i}",
                    "value": item if isinstance(item, (int, float)) else None,
                    "value_str": str(item) if not isinstance(item, (int, float)) else None,
                    "sequence": i
                })

        else:
            points.append({
                "timestamp": self.created_at,
                "metric": "value",
                "value": self._raw_data if isinstance(self._raw_data, (int, float)) else None,
                "value_str": str(self._raw_data),
                "sequence": 0
            })

        return points

    def as_vector(self) -> List[float]:
        return self._vector_form

    def as_nosql(self) -> Dict[str, Any]:
        return self._nosql_form

    def as_relational(self) -> Dict[str, Any]:
        return self._relational_form

    def as_timeseries(self) -> List[Dict[str, Any]]:
        return self._timeseries_form

    def in_language(self, language: StorageLanguage) -> Any:
        if language == StorageLanguage.VECTOR:
            return self.as_vector()
        elif language == StorageLanguage.NOSQL:
            return self.as_nosql()
        elif language == StorageLanguage.RELATIONAL:
            return self.as_relational()
        elif language == StorageLanguage.TIMESERIES:
            return self.as_timeseries()


# ============================================================================
# MODULE 3: OCTAHEDRON STORAGE BLOCKS
# ============================================================================

class OctahedronBlock:
    """
    Diamond-shaped storage block standing on one point.
    Forms the basic unit of the helix structure.
    """
    def __init__(self, center: Point3D, size: float, storage_type: StorageType,
                level: int, position: int):
        self.center = center
        self.size = size
        self.storage_type = storage_type
        self.level = level
        self.position = position
        self.data: Dict[str, QuadralingualPacket] = {}
        self.connections: List['OctahedronBlock'] = []
        self.access_points = self._calculate_access_points()

    def _calculate_access_points(self) -> List[Point3D]:
        """Calculate 6 vertices of octahedron"""
        half = self.size / 2
        return [
            Point3D(self.center.x, self.center.y + self.size, self.center.z),
            Point3D(self.center.x, self.center.y - self.size, self.center.z),
            Point3D(self.center.x + half, self.center.y, self.center.z + half),
            Point3D(self.center.x - half, self.center.y, self.center.z + half),
            Point3D(self.center.x + half, self.center.y, self.center.z - half),
            Point3D(self.center.x - half, self.center.y, self.center.z - half),
        ]

    def store_packet(self, packet: QuadralingualPacket):
        self.data[packet.packet_id] = packet

    def retrieve_packet(self, packet_id: str) -> Optional[QuadralingualPacket]:
        return self.data.get(packet_id)

    def connect_to(self, other: 'OctahedronBlock'):  # FIX: was 'delish connection...'
        """Establish connection to another block"""
        if other not in self.connections:
            self.connections.append(other)
        if self not in other.connections:
            other.connections.append(self)


# ============================================================================
# MODULE 4: DANDELION AI COORDINATOR
# ============================================================================

class DandelionAI:
    """
    Central AI coordinator at the center of the DNA spiral.
    Routes data through radial lanes to blocks.
    """
    def __init__(self, center: Point3D, num_lanes: int = 64):
        self.center = center
        self.num_lanes = num_lanes
        self.lanes = self._initialize_lanes()
        self.heat_level = 0.0
        self.active_connections: set = set()
        self.lock = Lock()

    def _initialize_lanes(self) -> List[Tuple[Point3D, List]]:
        lanes = []
        for i in range(self.num_lanes):
            angle = (i * 2 * math.pi) / self.num_lanes
            direction = Point3D(math.cos(angle), 0.5, math.sin(angle))
            lanes.append((direction, []))
        return lanes

    def increase_heat(self, load_factor: float):
        self.heat_level = min(1.0, self.heat_level + load_factor * 0.1)

    def decrease_heat(self):
        self.heat_level = max(0.0, self.heat_level - 0.05)

    def connect_blocks(self, blocks: List[OctahedronBlock]):
        with self.lock:
            for block in blocks:
                lane_idx = self._find_nearest_lane(block.center)
                self.lanes[lane_idx][1].append(block)
                self.active_connections.add((lane_idx, block.level, block.position))

    def _find_nearest_lane(self, target: Point3D) -> int:
        min_distance = float('inf')
        nearest = 0
        for i, (direction, _) in enumerate(self.lanes):
            distance = abs(
                (target.x - self.center.x) * direction.y -
                (target.y - self.center.y) * direction.x
            )
            if distance < min_distance:
                min_distance = distance
                nearest = i
        return nearest


# ============================================================================
# MODULE 5: DOUBLE HELIX STORAGE SYSTEM
# ============================================================================

class DoubleHelixStorage:
    def __init__(self, base_size: float = 1.0, spiral_radius: float = 10.0, drive_uuid: str = "a67ef4fb-bb2e-4e98-b60b-48e42c49e6a2"):
        self.base_size = base_size
        self.spiral_radius = spiral_radius
        self.blocks: List[List[OctahedronBlock]] = []
        self.dandelion = DandelionAI(Point3D(0, 0, 0))
        self.compression_factor = 1.0
        self.packet_registry: Dict[str, QuadralingualPacket] = {}
        self.lock = Lock()

    def _calculate_spiral_position(self, level: int, position: int) -> Point3D:
        """Calculate 3D position in DNA spiral"""
        golden_angle = 2 * math.pi * 0.618034
        angle = (level * golden_angle) + (position * math.pi / 2)
        radius = self.spiral_radius * self.compression_factor
        return Point3D(
            radius * math.cos(angle),
            level * self.base_size * 2 * self.compression_factor,
            radius * math.sin(angle)
        )

    def add_level(self, level: int):
        level_blocks = []
        storage_sequence = [
            StorageType.VECTOR,
            StorageType.NOSQL,
            StorageType.RELATIONAL,
            StorageType.TIME_SERIES
        ]
        for position in range(4):
            center = self._calculate_spiral_position(level, position)
            block = OctahedronBlock(
                center=center, size=self.base_size,
                storage_type=storage_sequence[position],
                level=level, position=position
            )
            level_blocks.append(block)
        with self.lock:
            if level >= len(self.blocks):
                self.blocks.append(level_blocks)
            else:
                self.blocks[level] = level_blocks
            self.dandelion.connect_blocks(level_blocks)
        self._establish_connections(level)

    def _establish_connections(self, level: int):
        if level >= len(self.blocks):
            return
        current_level = self.blocks[level]
        for i in range(4):
            current_level[i].connect_to(current_level[(i + 1) % 4])
        if level > 0:
            prev_level = self.blocks[level - 1]
            for i in range(4):
                current_level[i].connect_to(prev_level[i])
                current_level[i].connect_to(prev_level[(i + 1) % 4])

    def store(self, packet_id: str, data: Any,
                preferred_type: Optional[StorageType] = None) -> QuadralingualPacket:
        packet = QuadralingualPacket.from_data(packet_id, data)
        self.packet_registry[packet_id] = packet
        if preferred_type is None:
            if isinstance(data, (list, tuple)) and all(isinstance(x, (int, float)) for x in data):
                preferred_type = StorageType.VECTOR
            elif isinstance(data, dict):
                preferred_type = StorageType.NOSQL
            else:
                preferred_type = StorageType.RELATIONAL
        level = len(self.blocks) - 1 if self.blocks else -1
        if level < 0:
            self.add_level(0)
            level = 0
        for block in self.blocks[level]:
            if block.storage_type == preferred_type:
                block.store_packet(packet)
                break
        return packet

    def retrieve(self, packet_id: str,
                language: Optional[StorageLanguage] = None) -> Any:
        packet = self.packet_registry.get(packet_id)
        if not packet:
            for level_blocks in self.blocks:
                for block in level_blocks:
                    packet = block.retrieve_packet(packet_id)
                    if packet:
                        break
                if packet:
                    break
        if packet:
            if language:
                return packet.in_language(language)
            return packet._raw_data
        return None

    def query_language(self, language: StorageLanguage,
                        filter_func: Optional[Callable] = None) -> List[Any]:
        results = []
        for packet in self.packet_registry.values():
            data = packet.in_language(language)
            if filter_func is None or filter_func(data):
                results.append(data)
        return results

    def compress(self, load_factor: float):
        target = max(0.3, 1.0 - (load_factor * 0.7))
        self.compression_factor = target
        self.dandelion.increase_heat(load_factor)
        for level_idx, level_blocks in enumerate(self.blocks):
            for pos_idx, block in enumerate(level_blocks):
                block.center = self._calculate_spiral_position(level_idx, pos_idx)
                block.access_points = block._calculate_access_points()

    def expand(self):
        self.compression_factor = min(1.0, self.compression_factor + 0.1)
        self.dandelion.decrease_heat()
        for level_idx, level_blocks in enumerate(self.blocks):
            for pos_idx, block in enumerate(level_blocks):
                block.center = self._calculate_spiral_position(level_idx, pos_idx)
                block.access_points = block._calculate_access_points()

    def get_stats(self) -> Dict[str, Any]:
        total_blocks = sum(len(level) for level in self.blocks)
        storage_dist = defaultdict(int)
        for level_blocks in self.blocks:
            for block in level_blocks:
                storage_dist[block.storage_type.name] += 1
        return {
            "levels": len(self.blocks),
            "total_blocks": total_blocks,
            "total_packets": len(self.packet_registry),
            "compression_factor": self.compression_factor,
            "dandelion_heat": self.dandelion.heat_level,
            "active_lanes": len(self.dandelion.active_connections),
            "storage_distribution": dict(storage_dist)
        }


# ============================================================================
# MODULE 6: HIGH-LEVEL API
# ============================================================================

class HelixDB:
    def __init__(self, initial_levels: int = 5):
        self.helix = DoubleHelixStorage()
        for i in range(initial_levels):
            self.helix.add_level(i)

    def store_vector(self, key: str, vector: List[float]) -> QuadralingualPacket:
        return self.helix.store(key, vector, StorageType.VECTOR)

    def get_vector(self, key: str) -> List[float]:
        return self.helix.retrieve(key, StorageLanguage.VECTOR)

    def store_document(self, key: str, document: Dict) -> QuadralingualPacket:
        return self.helix.store(key, document, StorageType.NOSQL)

    def get_document(self, key: str) -> Dict:
        return self.helix.retrieve(key, StorageLanguage.NOSQL)

    def store_row(self, key: str, row: Dict) -> QuadralingualPacket:
        return self.helix.store(key, row, StorageType.RELATIONAL)

    def get_row(self, key: str) -> Dict:
        return self.helix.retrieve(key, StorageLanguage.RELATIONAL)

    def store_timeseries(self, key: str, data: Dict) -> QuadralingualPacket:
        return self.helix.store(key, data, StorageType.TIME_SERIES)

    def get_timeseries(self, key: str) -> List[Dict]:
        return self.helix.retrieve(key, StorageLanguage.TIMESERIES)

    def store(self, key: str, data: Any) -> QuadralingualPacket:
        return self.helix.store(key, data)

    def get(self, key: str, as_language: Optional[StorageLanguage] = None) -> Any:
        return self.helix.retrieve(key, as_language)

    def query(self, language: StorageLanguage, filter_func: Optional[Callable] = None) -> List:
        return self.helix.query_language(language, filter_func)

    def handle_load(self, load_factor: float):
        if load_factor > 0.5:
            self.helix.compress(load_factor)
        else:
            self.helix.expand()

    def stats(self) -> Dict:
        return self.helix.get_stats()


# ============================================================================
# MODULE 7: DEMO & TESTING
# ============================================================================

def demo():
    print("=" * 70)
    print("🧬 STANDALONE MODULAR DOUBLE HELIX STORAGE SYSTEM")
    print("=" * 70)

    db = HelixDB(initial_levels=5)
    print("✓ System ready\n")

    db.store_vector("vec1", [1.0, 2.0, 3.0, 4.0, 5.0])
    db.store_document("doc1", {"user_id": 42, "name": "Alice", "score": 95.5})
    db.store_row("row1", {"id": 1, "product": "Widget", "price": 29.99})
    db.store_timeseries("ts1", {"timestamp": time.time(), "temperature": 22.5, "humidity": 60})
    print("✓ All data stored\n")

    print("doc1 as VECTOR:", db.get("doc1", StorageLanguage.VECTOR))
    print("doc1 as NOSQL:", json.dumps(db.get("doc1", StorageLanguage.NOSQL), indent=2))

    db.handle_load(0.9)
    stats = db.stats()
    print(f"\nUnder load — compression: {stats['compression_factor']:.2f}, heat: {stats['dandelion_heat']:.2f}")

    db.handle_load(0.2)
    stats = db.stats()
    print(f"Relaxed    — compression: {stats['compression_factor']:.2f}, heat: {stats['dandelion_heat']:.2f}")

    print("\n" + "=" * 70)
    print("🎉 DEMO COMPLETE!")
    print("=" * 70)


if __name__ == "__main__":
    demo()
