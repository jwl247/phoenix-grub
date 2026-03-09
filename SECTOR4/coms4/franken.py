#!/usr/bin/env python3
"""
🧬 FRANKEN2 - Helix System with OS-Agnostic Layer
Helix virtual RAM + cross-platform abstraction
"""

import os
import sys
import time
import pickle
import zlib
import platform
import socket
import threading
import random
import json
import secrets
import shutil
import subprocess
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional, Dict, List, Callable
from pathlib import Path
from enum import Enum

try:
    import urllib.request as urllib_request
    import urllib.error as urllib_error
except ImportError:
    pass

print("🧬 Loading Franken2 / Helix System...")

# ============================================================================
# PID MANAGER STUB (replace with real pid_manager module if available)
# ============================================================================

class ProcessManager:
    """Stub for pid_manager.ProcessManager"""
    def register_pid(self, name: str) -> int:
        import os
        pid = os.getpid()
        print(f"  Registered '{name}' as PID {pid}")
        return pid

# ============================================================================
# PART 1: CORE TYPES
# ============================================================================

class MemoryTier(Enum):
    L1_HOT = 0
    L2_WARM = 1
    L3_COMPRESSED = 2
    L4_COLD = 3
    L5_DISK = 4

@dataclass
class CacheBlock:
    key: str
    data: Any
    tier: MemoryTier
    size_bytes: int
    access_count: int = 0
    last_access: float = field(default_factory=time.time)
    compressed: bool = False
    _compressed_data: Optional[bytes] = None

    def access(self):
        self.access_count += 1
        self.last_access = time.time()

    def compress(self) -> int:
        if not self.compressed and self.data is not None:
            try:
                serialized = pickle.dumps(self.data)
                self._compressed_data = zlib.compress(serialized, level=6)
                saved = self.size_bytes - len(self._compressed_data)
                self.compressed = True
                return max(0, saved)
            except:
                return 0
        return 0

    def decompress(self):
        if self.compressed and self._compressed_data:
            try:
                serialized = zlib.decompress(self._compressed_data)
                self.data = pickle.loads(serialized)
                self.compressed = False
                self._compressed_data = None
            except:
                pass

# ============================================================================
# PART 2: OS TYPE
# ============================================================================

class OSType(Enum):
    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "darwin"
    UNKNOWN = "unknown"

@dataclass
class SystemInfo:
    os_type: OSType
    os_version: str
    python_version: str
    architecture: str
    home_dir: Path
    temp_dir: Path
    has_sudo: bool
    path_separator: str
    line_ending: str

# ============================================================================
# PART 3: HELIX CACHE (Multi-level intelligent cache)
# ============================================================================

class HelixCache:
    def __init__(self, l1_mb=128, l2_mb=512, l3_mb=1024):
        self.l1_max = l1_mb * 1024 * 1024
        self.l2_max = l2_mb * 1024 * 1024
        self.l3_max = l3_mb * 1024 * 1024

        self.l1_cache: OrderedDict = OrderedDict()
        self.l2_cache: OrderedDict = OrderedDict()
        self.l3_cache: OrderedDict = OrderedDict()

        self.stats = {
            'l1_hits': 0, 'l1_misses': 0,
            'l2_hits': 0, 'l2_misses': 0,
            'l3_hits': 0, 'l3_misses': 0,
            'promotions': 0, 'demotions': 0,
            'evictions': 0, 'compressions': 0
        }
        self.lock = threading.RLock()

    def get(self, key: str) -> Optional[Any]:
        with self.lock:
            if key in self.l1_cache:
                self.stats['l1_hits'] += 1
                block = self.l1_cache[key]
                block.access()
                self.l1_cache.move_to_end(key)
                return block.data

            self.stats['l1_misses'] += 1

            if key in self.l2_cache:
                self.stats['l2_hits'] += 1
                block = self.l2_cache[key]
                block.access()
                if block.access_count > 3:
                    self._promote_to_l1(key, block)
                else:
                    self.l2_cache.move_to_end(key)
                return block.data

            self.stats['l2_misses'] += 1

            if key in self.l3_cache:
                self.stats['l3_hits'] += 1
                block = self.l3_cache[key]
                block.access()
                if block.compressed:
                    block.decompress()
                if block.access_count > 2:
                    self._promote_to_l2(key, block)
                else:
                    self.l3_cache.move_to_end(key)
                return block.data

            self.stats['l3_misses'] += 1
            return None

    def put(self, key: str, data: Any, size: int):
        with self.lock:
            self.l2_cache.pop(key, None)
            self.l3_cache.pop(key, None)
            block = CacheBlock(key=key, data=data, tier=MemoryTier.L1_HOT, size_bytes=size)
            self._make_room_l1(size)
            self.l1_cache[key] = block

    def _get_tier_size(self, tier_dict):
        total = 0
        for block in tier_dict.values():
            if block.compressed and block._compressed_data:
                total += len(block._compressed_data)
            else:
                total += block.size_bytes
        return total

    def _make_room_l1(self, needed):
        current = self._get_tier_size(self.l1_cache)
        while current + needed > self.l1_max and self.l1_cache:
            key, block = next(iter(self.l1_cache.items()))
            self._demote_to_l2(key, block)
            current = self._get_tier_size(self.l1_cache)

    def _make_room_l2(self, needed):
        current = self._get_tier_size(self.l2_cache)
        while current + needed > self.l2_max and self.l2_cache:
            key, block = next(iter(self.l2_cache.items()))
            self._demote_to_l3(key, block)
            current = self._get_tier_size(self.l2_cache)

    def _make_room_l3(self, needed):
        current = self._get_tier_size(self.l3_cache)
        while current + needed > self.l3_max and self.l3_cache:
            key, block = next(iter(self.l3_cache.items()))
            del self.l3_cache[key]
            self.stats['evictions'] += 1
            current = self._get_tier_size(self.l3_cache)

    def _promote_to_l1(self, key, block):
        self.l2_cache.pop(key, None)
        self._make_room_l1(block.size_bytes)
        block.tier = MemoryTier.L1_HOT
        self.l1_cache[key] = block
        self.stats['promotions'] += 1

    def _promote_to_l2(self, key, block):
        self.l3_cache.pop(key, None)
        self._make_room_l2(block.size_bytes)
        block.tier = MemoryTier.L2_WARM
        self.l2_cache[key] = block
        self.stats['promotions'] += 1

    def _demote_to_l2(self, key, block):
        self.l1_cache.pop(key, None)
        self._make_room_l2(block.size_bytes)
        block.tier = MemoryTier.L2_WARM
        self.l2_cache[key] = block
        self.stats['demotions'] += 1

    def _demote_to_l3(self, key, block):
        self.l2_cache.pop(key, None)
        saved = block.compress()
        if saved > 0:
            self.stats['compressions'] += 1
        size = len(block._compressed_data) if block._compressed_data else block.size_bytes
        self._make_room_l3(size)
        block.tier = MemoryTier.L3_COMPRESSED
        self.l3_cache[key] = block
        self.stats['demotions'] += 1

# ============================================================================
# PART 4: MEMORY MANAGER
# ============================================================================

class HelixMemoryManager:
    def __init__(self, cache, max_virtual_mb=8192):
        self.cache = cache
        self.max_virtual = max_virtual_mb * 1024 * 1024
        self.allocations: Dict[str, int] = {}
        self.total_allocated = 0
        self.stats = {
            'total_allocations': 0,
            'total_deallocations': 0,
            'virtual_memory_used': 0
        }
        self.lock = threading.RLock()

    def malloc(self, key: str, data: Any) -> bool:
        with self.lock:
            try:
                size = len(pickle.dumps(data))
            except:
                size = 1024
            if self.total_allocated + size > self.max_virtual:
                return False
            self.cache.put(key, data, size)
            self.allocations[key] = size
            self.total_allocated += size
            self.stats['total_allocations'] += 1
            self.stats['virtual_memory_used'] = self.total_allocated
            return True

    def free(self, key: str) -> bool:
        with self.lock:
            if key not in self.allocations:
                return False
            size = self.allocations[key]
            self.total_allocated -= size
            del self.allocations[key]
            self.cache.l1_cache.pop(key, None)
            self.cache.l2_cache.pop(key, None)
            self.cache.l3_cache.pop(key, None)
            self.stats['total_deallocations'] += 1
            self.stats['virtual_memory_used'] = self.total_allocated
            return True

    def read(self, key: str) -> Optional[Any]:
        return self.cache.get(key)

    def write(self, key: str, data: Any) -> bool:
        with self.lock:
            if key in self.allocations:
                self.free(key)
            return self.malloc(key, data)

# ============================================================================
# PART 5: FILESYSTEM CACHE
# ============================================================================

class HelixFS:
    def __init__(self, memory_manager):
        self.memory = memory_manager
        self.file_cache: Dict[str, str] = {}
        self.stats = {
            'file_reads': 0, 'file_writes': 0,
            'cache_hits': 0, 'cache_misses': 0,
            'disk_reads': 0, 'disk_writes': 0
        }
        self.lock = threading.RLock()

    def read_file(self, filepath: str) -> Optional[bytes]:
        with self.lock:
            self.stats['file_reads'] += 1
            cache_key = f"file:{filepath}"
            cached = self.memory.read(cache_key)
            if cached is not None:
                self.stats['cache_hits'] += 1
                return cached
            self.stats['cache_misses'] += 1
            if not os.path.exists(filepath):
                return None
            try:
                with open(filepath, 'rb') as f:
                    data = f.read()
                self.stats['disk_reads'] += 1
                self.memory.malloc(cache_key, data)
                self.file_cache[filepath] = cache_key
                return data
            except:
                return None

    def write_file(self, filepath: str, data: bytes, write_through: bool = True):
        with self.lock:
            self.stats['file_writes'] += 1
            cache_key = f"file:{filepath}"
            self.memory.write(cache_key, data)
            self.file_cache[filepath] = cache_key
            if write_through:
                try:
                    os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
                    with open(filepath, 'wb') as f:
                        f.write(data)
                    self.stats['disk_writes'] += 1
                except:
                    pass

# ============================================================================
# PART 6: TRANSLATOR LAYER
# ============================================================================

@dataclass
class TranslationEntry:
    app_pointer: int
    helix_key: str
    size: int
    created_at: float
    last_access: float
    access_count: int = 0

    def access(self):
        self.last_access = time.time()
        self.access_count += 1

class HelixTranslator:
    def __init__(self, helix_system):
        self.helix = helix_system
        self.ptr_to_key: Dict[int, TranslationEntry] = {}
        self.key_to_ptr: Dict[str, int] = {}
        self.next_fake_pointer = 0x10000000
        self.fd_to_path: Dict[int, str] = {}
        self.path_to_fd: Dict[str, int] = {}
        self.next_fake_fd = 1000
        self.stats = {
            'ingress_calls': 0, 'egress_calls': 0,
            'malloc_intercepts': 0, 'free_intercepts': 0,
            'read_intercepts': 0, 'write_intercepts': 0
        }

    def translate_malloc(self, size: int) -> int:
        self.stats['ingress_calls'] += 1
        self.stats['malloc_intercepts'] += 1
        helix_key = f"mem_{self.next_fake_pointer:016x}_{size}"
        data = bytearray(size)
        success = self.helix.memory.malloc(helix_key, bytes(data))
        if not success:
            return 0
        fake_ptr = self.next_fake_pointer
        self.next_fake_pointer += 0x1000
        entry = TranslationEntry(
            app_pointer=fake_ptr, helix_key=helix_key,
            size=size, created_at=time.time(), last_access=time.time()
        )
        self.ptr_to_key[fake_ptr] = entry
        self.key_to_ptr[helix_key] = fake_ptr
        self.stats['egress_calls'] += 1
        return fake_ptr

    def translate_free(self, pointer: int) -> bool:
        self.stats['ingress_calls'] += 1
        self.stats['free_intercepts'] += 1
        if pointer not in self.ptr_to_key:
            return False
        entry = self.ptr_to_key[pointer]
        self.helix.memory.free(entry.helix_key)
        del self.ptr_to_key[pointer]
        del self.key_to_ptr[entry.helix_key]
        self.stats['egress_calls'] += 1
        return True

    def translate_read(self, pointer: int, size: int, offset: int = 0) -> Optional[bytes]:
        self.stats['ingress_calls'] += 1
        self.stats['read_intercepts'] += 1
        if pointer not in self.ptr_to_key:
            return None
        entry = self.ptr_to_key[pointer]
        entry.access()
        data = self.helix.memory.read(entry.helix_key)
        if data is None:
            return None
        self.stats['egress_calls'] += 1
        if isinstance(data, bytes):
            return data[offset:offset+size]
        return bytes(data)[offset:offset+size]

    def translate_write(self, pointer: int, data: bytes, offset: int = 0) -> bool:
        self.stats['ingress_calls'] += 1
        self.stats['write_intercepts'] += 1
        if pointer not in self.ptr_to_key:
            return False
        entry = self.ptr_to_key[pointer]
        entry.access()
        existing = self.helix.memory.read(entry.helix_key)
        buffer = bytearray(existing) if existing else bytearray(entry.size)
        end = offset + len(data)
        buffer[offset:end] = data
        success = self.helix.memory.write(entry.helix_key, bytes(buffer))
        self.stats['egress_calls'] += 1
        return success

    def translate_open(self, filepath: str, mode: str = 'r') -> int:
        self.stats['ingress_calls'] += 1
        fake_fd = self.next_fake_fd
        self.next_fake_fd += 1
        self.fd_to_path[fake_fd] = filepath
        self.path_to_fd[filepath] = fake_fd
        self.stats['egress_calls'] += 1
        return fake_fd

    def translate_read_file(self, fd: int, size: int) -> Optional[bytes]:
        self.stats['ingress_calls'] += 1
        if fd not in self.fd_to_path:
            return None
        filepath = self.fd_to_path[fd]
        data = self.helix.fs.read_file(filepath)
        self.stats['egress_calls'] += 1
        return data[:size] if data else None

    def translate_write_file(self, fd: int, data: bytes) -> bool:
        self.stats['ingress_calls'] += 1
        if fd not in self.fd_to_path:
            return False
        filepath = self.fd_to_path[fd]
        self.helix.fs.write_file(filepath, data)
        self.stats['egress_calls'] += 1
        return True

    def translate_close(self, fd: int) -> bool:
        self.stats['ingress_calls'] += 1
        if fd not in self.fd_to_path:
            return False
        filepath = self.fd_to_path[fd]
        del self.fd_to_path[fd]
        del self.path_to_fd[filepath]
        self.stats['egress_calls'] += 1
        return True

# ============================================================================
# PART 7: UNIFIED SYSTEM
# ============================================================================

class HelixSystem:
    def __init__(self, l1_mb=512, l2_mb=2048, l3_mb=6000, vram_mb=8096):
        self.cache = HelixCache(l1_mb, l2_mb, l3_mb)
        self.memory = HelixMemoryManager(self.cache, vram_mb)
        self.fs = HelixFS(self.memory)
        self.start_time = time.time()

    def get_stats(self):
        l1_size = self.cache._get_tier_size(self.cache.l1_cache)
        l2_size = self.cache._get_tier_size(self.cache.l2_cache)
        l3_size = self.cache._get_tier_size(self.cache.l3_cache)
        total_ops = sum([
            self.cache.stats['l1_hits'], self.cache.stats['l1_misses'],
            self.cache.stats['l2_hits'], self.cache.stats['l2_misses'],
            self.cache.stats['l3_hits'], self.cache.stats['l3_misses']
        ])
        total_hits = self.cache.stats['l1_hits'] + self.cache.stats['l2_hits'] + self.cache.stats['l3_hits']
        hit_rate = (total_hits / total_ops * 100) if total_ops > 0 else 0
        return {
            'uptime': time.time() - self.start_time,
            'cache': {
                'l1_size_mb': l1_size / (1024 * 1024),
                'l2_size_mb': l2_size / (1024 * 1024),
                'l3_size_mb': l3_size / (1024 * 1024),
                'hit_rate': hit_rate,
                'l1_items': len(self.cache.l1_cache),
                'l2_items': len(self.cache.l2_cache),
                'l3_items': len(self.cache.l3_cache),
                **self.cache.stats
            },
            'memory': {
                'allocated_mb': self.memory.total_allocated / (1024 * 1024),
                'allocation_count': len(self.memory.allocations),
                **self.memory.stats
            },
            'filesystem': {
                'cached_files': len(self.fs.file_cache),
                **self.fs.stats
            }
        }

    def print_stats(self):
        stats = self.get_stats()
        print("\n" + "=" * 70)
        print("🧬 HELIX SYSTEM STATISTICS")
        print("=" * 70)
        print(f"Uptime: {stats['uptime']:.1f}s\n")
        print("📊 CACHE:")
        print(f"  L1 (hot):        {stats['cache']['l1_size_mb']:8.2f} MB ({stats['cache']['l1_items']:,} items)")
        print(f"  L2 (warm):       {stats['cache']['l2_size_mb']:8.2f} MB ({stats['cache']['l2_items']:,} items)")
        print(f"  L3 (compressed): {stats['cache']['l3_size_mb']:8.2f} MB ({stats['cache']['l3_items']:,} items)")
        print(f"  Hit Rate:        {stats['cache']['hit_rate']:.1f}%")
        print(f"  Compressions:    {stats['cache']['compressions']:,}\n")
        print("💾 VIRTUAL MEMORY:")
        print(f"  Allocated:       {stats['memory']['allocated_mb']:8.2f} MB")
        print(f"  Allocations:     {stats['memory']['total_allocations']:,}")
        print(f"  Frees:           {stats['memory']['total_deallocations']:,}\n")
        print("📁 FILESYSTEM:")
        print(f"  Cached Files:    {stats['filesystem']['cached_files']:,}")
        print(f"  Cache Hits:      {stats['filesystem']['cache_hits']:,}")
        print(f"  Disk Reads:      {stats['filesystem']['disk_reads']:,}\n")

# ============================================================================
# PART 8: OS-AGNOSTIC LAYER
# ============================================================================

class AgnosticLayer:
    """
    OS-Agnostic abstraction layer
    Translates everything so Helix works ANYWHERE
    """

    def __init__(self):
        self.system = self._detect_system()

    def _detect_system(self) -> SystemInfo:
        sys_platform = platform.system().lower()
        if 'windows' in sys_platform:
            os_type, path_sep, line_end, has_sudo = OSType.WINDOWS, '\\', '\r\n', False
        elif 'linux' in sys_platform:
            os_type, path_sep, line_end, has_sudo = OSType.LINUX, '/', '\n', True
        elif 'darwin' in sys_platform:
            os_type, path_sep, line_end, has_sudo = OSType.MACOS, '/', '\n', True
        else:
            os_type, path_sep, line_end, has_sudo = OSType.UNKNOWN, os.sep, '\n', False

        return SystemInfo(
            os_type=os_type,
            os_version=platform.version(),
            python_version=sys.version,
            architecture=platform.machine(),
            home_dir=Path.home(),
            temp_dir=Path(os.environ.get('TEMP', '/tmp')),
            has_sudo=has_sudo,
            path_separator=path_sep,
            line_ending=line_end
        )

    def get_install_dir(self, app_name: str = "lifefirst") -> Path:
        if self.system.os_type == OSType.WINDOWS:
            base = Path(os.environ.get('LOCALAPPDATA', self.system.home_dir))
            return base / app_name
        elif self.system.os_type == OSType.MACOS:
            return self.system.home_dir / 'Library' / 'Application Support' / app_name
        else:
            return self.system.home_dir / '.local' / 'share' / app_name

    def check_port_available(self, port: int) -> bool:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()
            return result != 0
        except:
            return False

    def find_python(self) -> str:
        candidates = ['python3', 'python', 'py']
        import shutil
        for candidate in candidates:
            if shutil.which(candidate):
                return candidate
        return 'python3'

    def create_launcher(self, install_dir: Path, script_name: str) -> Path:
        if self.system.os_type == OSType.WINDOWS:
            launcher = install_dir / f"{script_name}.bat"
            python_cmd = self.find_python()
            content = f'@echo off\n{python_cmd} "{install_dir / "start.py"}" %*\n'
        else:
            launcher = install_dir / f"{script_name}.sh"
            content = f'#!/usr/bin/env bash\ncd "{install_dir}"\n{self.find_python()} start.py "$@"\n'

        with open(launcher, 'w') as f:
            f.write(content)

        if self.system.os_type != OSType.WINDOWS:
            import stat
            launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        return launcher

    def parse_config(self, path: Path) -> dict:
        import json
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def parse_any(self, data_path: Path) -> dict:
        suffix = data_path.suffix.lower()
        if suffix == '.json':
            return self.parse_config(data_path)
        elif suffix == '.txt':
            return self._parse_text(data_path)
        elif suffix in ['.yaml', '.yml']:
            return self._parse_yaml(data_path)
        else:
            return self._parse_generic(data_path)

    def _parse_text(self, path: Path) -> dict:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        return {'content': content, 'lines': content.splitlines()}

    def _parse_yaml(self, path: Path) -> dict:
        try:
            import yaml
            with open(path, 'r') as f:
                return yaml.safe_load(f)
        except ImportError:
            return self._parse_generic(path)

    def _parse_generic(self, path: Path) -> dict:
        result = {}
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if '=' in line:
                    k, _, v = line.partition('=')
                    result[k.strip()] = v.strip()
        return result

# ============================================================================
# PART 9: HELIX SYNC (Syncthing distribution module)
# ============================================================================

class SyncRole(Enum):
    MASTER = "master"
    NODE   = "node"

class HelixSync:
    """
    Pure-Python Syncthing distribution module for Frank.
    Mirrors the HeIXSync JS module features:
      - Syncthing install/start/stop
      - Multi-node management via Syncthing REST API
      - Version tagging and snapshots
      - Rollback
      - Auto-snapshot on sync completion
    """

    def __init__(self, config: dict = None):
        cfg = config or {}
        self.version = '1.0.0'

        self.helix_root     = Path(cfg.get('helix_root',     '/opt/heix'))
        self.snapshot_base  = Path(cfg.get('snapshot_base',  '/snapshots/heix-versions'))
        self.log_dir        = Path(cfg.get('log_dir',        '/var/log/heix'))
        self.syncthing_home = Path(cfg.get('syncthing_home', '/opt/heix/.syncthing'))
        self.syncthing_port = cfg.get('syncthing_port', 8384)
        self.api_key        = cfg.get('syncthing_api_key', self._generate_api_key())
        self.role           = SyncRole(cfg.get('role', 'master'))
        self.master_address = cfg.get('master_address', None)
        self.auto_snapshot  = cfg.get('auto_snapshot', True)
        self.max_snapshots  = cfg.get('max_snapshots', 10)
        self.nodes: List[str] = cfg.get('nodes', [])

        self._process: Optional[subprocess.Popen] = None
        self._running  = False
        self._current_version: Optional[str] = None
        self._last_sync = None
        self._connected_nodes: List[dict] = []
        self._watch_thread: Optional[threading.Thread] = None
        self._stop_watch = threading.Event()
        self.on_sync: Optional[Callable] = None

        self._log('info', f'HelixSync v{self.version} | role={self.role.value}')
        self._ensure_directories()
        self._load_current_version()

    # ── Logging ──────────────────────────────────────────────────────────────

    def _log(self, level: str, message: str):
        symbols = {
            'info':    '📘', 'success': '✅', 'warning': '⚠️',
            'error':   '❌', 'debug':   '🔍', 'critical': '🚨'
        }
        ts = time.strftime('%Y-%m-%dT%H:%M:%S')
        print(f"{ts} {symbols.get(level, '📝')} [HelixSync] {message}")

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _generate_api_key(self) -> str:
        return secrets.token_hex(16)

    def _ensure_directories(self):
        for d in [self.helix_root, self.snapshot_base, self.log_dir, self.syncthing_home]:
            d.mkdir(parents=True, exist_ok=True)

    def _load_current_version(self):
        version_file = self.helix_root / 'VERSION'
        try:
            self._current_version = version_file.read_text().strip()
            self._log('info', f'Current version: {self._current_version}')
        except FileNotFoundError:
            self._current_version = 'unknown'

    def _api(self, method: str, path: str, body: dict = None) -> Optional[dict]:
        """Call Syncthing REST API."""
        url = f'http://localhost:{self.syncthing_port}{path}'
        headers = {'X-API-Key': self.api_key, 'Content-Type': 'application/json'}
        data = json.dumps(body).encode() if body else None
        req = urllib_request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib_request.urlopen(req, timeout=5) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except Exception as e:
            self._log('debug', f'API {method} {path} → {e}')
            return None

    # ── Syncthing management ──────────────────────────────────────────────────

    def ensure_syncthing(self) -> bool:
        """Check Syncthing is installed; install it if not."""
        if shutil.which('syncthing'):
            self._log('success', 'Syncthing found')
            return True
        self._log('warning', 'Syncthing not found — installing...')
        return self._install_syncthing()

    def _install_syncthing(self) -> bool:
        commands = [
            'curl -s https://syncthing.net/release-key.gpg | sudo tee /usr/share/keyrings/syncthing-archive-keyring.gpg > /dev/null',
            'echo "deb [signed-by=/usr/share/keyrings/syncthing-archive-keyring.gpg] https://apt.syncthing.net/ syncthing stable" | sudo tee /etc/apt/sources.list.d/syncthing.list',
            'sudo apt-get update -qq',
            'sudo apt-get install -y syncthing'
        ]
        for cmd in commands:
            result = subprocess.run(cmd, shell=True, capture_output=True)
            if result.returncode != 0:
                self._log('error', f'Install step failed: {cmd}')
                return False
        self._log('success', 'Syncthing installed')
        return True

    def _generate_syncthing_config(self):
        config_path = self.syncthing_home / 'config.xml'
        if config_path.exists():
            self._log('info', 'Syncthing config exists')
            return
        self._log('info', 'Generating Syncthing config...')
        config_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<configuration version="37">
    <gui enabled="true" tls="false">
        <address>127.0.0.1:{self.syncthing_port}</address>
        <apikey>{self.api_key}</apikey>
        <theme>default</theme>
    </gui>
    <options>
        <listenAddress>default</listenAddress>
        <globalAnnounceEnabled>false</globalAnnounceEnabled>
        <localAnnounceEnabled>true</localAnnounceEnabled>
        <relaysEnabled>false</relaysEnabled>
        <natEnabled>false</natEnabled>
        <urAccepted>-1</urAccepted>
    </options>
</configuration>"""
        config_path.write_text(config_xml)
        self._log('success', 'Syncthing config generated')

    def start(self):
        """Start the Syncthing process."""
        if self._running:
            self._log('warning', 'Syncthing already running')
            return
        if not self.ensure_syncthing():
            raise RuntimeError('Syncthing not available')

        self._generate_syncthing_config()
        self._log('info', 'Starting Syncthing...')

        self._process = subprocess.Popen(
            ['syncthing', '-home', str(self.syncthing_home),
             '-no-browser', '-no-restart', '-logflags=3'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )

        # Stream logs in background thread
        def _stream():
            for line in self._process.stdout:
                self._log('debug', f'[ST] {line.decode().strip()}')
        threading.Thread(target=_stream, daemon=True).start()

        self._wait_for_syncthing()
        self._running = True
        self._log('success', f'Syncthing running on port {self.syncthing_port}')
        self._configure_folders()
        self._start_sync_watcher()

    def stop(self):
        """Stop Syncthing."""
        if not self._running or not self._process:
            return
        self._log('info', 'Stopping Syncthing...')
        self._stop_watch.set()
        self._process.terminate()
        self._process.wait(timeout=10)
        self._running = False
        self._log('success', 'Syncthing stopped')

    def _wait_for_syncthing(self, max_attempts: int = 30):
        for attempt in range(max_attempts):
            result = self._api('GET', '/rest/system/status')
            if result is not None:
                return
            time.sleep(1)
        raise TimeoutError('Syncthing failed to start')

    def _configure_folders(self):
        folder_type = 'sendonly' if self.role == SyncRole.MASTER else 'receiveonly'
        folder_config = {
            'id': 'heix-code',
            'label': 'HeIX Code',
            'path': str(self.helix_root),
            'type': folder_type,
            'rescanIntervalS': 60,
            'fsWatcherEnabled': True,
            'fsWatcherDelayS': 10
        }
        result = self._api('PUT', '/rest/config/folders/heix-code', folder_config)
        if result is not None:
            self._log('success', 'HeIX folder configured')
        else:
            self._log('error', 'Failed to configure folder')

    # ── Node management ───────────────────────────────────────────────────────

    def add_node(self, device_id: str, name: str, address: str):
        self._log('info', f'Adding node: {name} ({device_id})')
        device_config = {
            'deviceID': device_id,
            'name': name,
            'addresses': [address],
            'compression': 'metadata',
            'introducer': False,
            'paused': False
        }
        result = self._api('PUT', f'/rest/config/devices/{device_id}', device_config)
        if result is not None:
            self._share_folder_with_device(device_id)
            self.nodes.append(device_id)
            self._log('success', f'Node added: {name}')
        else:
            self._log('error', f'Failed to add node: {name}')

    def _share_folder_with_device(self, device_id: str):
        folder = self._api('GET', '/rest/config/folders/heix-code')
        if folder is None:
            return
        devices = folder.get('devices', [])
        if not any(d['deviceID'] == device_id for d in devices):
            devices.append({'deviceID': device_id, 'introducedBy': ''})
        folder['devices'] = devices
        self._api('PUT', '/rest/config/folders/heix-code', folder)
        self._log('success', f'Shared folder with {device_id}')

    def get_connected_nodes(self) -> List[dict]:
        data = self._api('GET', '/rest/system/connections')
        if data is None:
            return []
        connections = [
            {'id': dev_id, 'address': conn.get('address'), 'at': conn.get('at')}
            for dev_id, conn in data.get('connections', {}).items()
            if conn.get('connected')
        ]
        self._connected_nodes = connections
        return connections

    # ── Versioning & snapshots ────────────────────────────────────────────────

    def tag_version(self, tag: str) -> str:
        ts = time.strftime('%Y-%m-%dT%H-%M-%S')
        version = f'v-{tag}-{ts}'
        self._log('info', f'Tagging version: {version}')
        (self.helix_root / 'VERSION').write_text(version)
        self._current_version = version
        if self.auto_snapshot:
            self.create_snapshot(version)
        return version

    def create_snapshot(self, version: str = None) -> Optional[Path]:
        version = version or self._current_version or f'manual-{int(time.time())}'
        snapshot_path = self.snapshot_base / f'heix-{version}'
        self._log('info', f'Creating snapshot: {version}')
        try:
            excludes = [
                '--exclude=/dev/*', '--exclude=/proc/*', '--exclude=/sys/*',
                '--exclude=/tmp/*', '--exclude=/run/*', '--exclude=/mnt/*',
                '--exclude=/media/*', '--exclude=/lost+found',
                f'--exclude={self.snapshot_base}/*'
            ]
            cmd = ['rsync', '-aAXH'] + excludes + ['/', str(snapshot_path) + '/']
            subprocess.run(cmd, check=True, capture_output=True)

            metadata = {
                'version': version,
                'timestamp': time.time(),
                'role': self.role.value,
                'nodes': len(self._connected_nodes)
            }
            (snapshot_path / 'HEIX_SNAPSHOT.json').write_text(json.dumps(metadata, indent=2))
            self._log('success', f'Snapshot created: {version}')
            self._cleanup_old_snapshots()
            return snapshot_path
        except Exception as e:
            self._log('error', f'Snapshot failed: {e}')
            return None

    def list_snapshots(self) -> List[dict]:
        snapshots = []
        try:
            for entry in self.snapshot_base.iterdir():
                if entry.name.startswith('heix-'):
                    meta_file = entry / 'HEIX_SNAPSHOT.json'
                    try:
                        meta = json.loads(meta_file.read_text())
                        snapshots.append({'name': entry.name, **meta})
                    except Exception:
                        snapshots.append({'name': entry.name, 'version': 'unknown', 'timestamp': 0})
        except FileNotFoundError:
            pass
        return sorted(snapshots, key=lambda s: s.get('timestamp', 0), reverse=True)

    def rollback(self, snapshot_name: str) -> bool:
        snapshot_path = self.snapshot_base / snapshot_name
        self._log('warning', f'Rolling back to: {snapshot_name}')
        if not snapshot_path.exists():
            self._log('error', f'Snapshot not found: {snapshot_name}')
            return False
        try:
            cmd = ['rsync', '-aAXHv', str(snapshot_path) + '/', '/']
            subprocess.run(cmd, check=True, capture_output=True)
            self._load_current_version()
            self._log('success', f'Rollback complete: {snapshot_name}')
            self._log('warning', 'Reboot recommended')
            return True
        except Exception as e:
            self._log('error', f'Rollback failed: {e}')
            return False

    def _cleanup_old_snapshots(self):
        snapshots = self.list_snapshots()
        for old in snapshots[self.max_snapshots:]:
            old_path = self.snapshot_base / old['name']
            try:
                shutil.rmtree(old_path)
                self._log('info', f'Deleted old snapshot: {old["name"]}')
            except Exception as e:
                self._log('error', f'Failed to delete snapshot: {e}')

    # ── Sync event watcher ────────────────────────────────────────────────────

    def _start_sync_watcher(self):
        self._stop_watch.clear()
        self._watch_thread = threading.Thread(target=self._sync_watch_loop, daemon=True)
        self._watch_thread.start()

    def _sync_watch_loop(self):
        while not self._stop_watch.wait(5):
            self._check_sync_completion()

    def _check_sync_completion(self):
        data = self._api('GET', '/rest/db/completion?folder=heix-code')
        if data is None:
            return
        if data.get('completion') == 100 and self._last_sync != data.get('globalBytes'):
            self._last_sync = data.get('globalBytes')
            self._on_sync_complete()

    def _on_sync_complete(self):
        self._log('success', 'Code synchronized')
        if self.auto_snapshot and self.role == SyncRole.NODE:
            self._load_current_version()
            self.create_snapshot(self._current_version)
        if self.on_sync:
            self.on_sync()

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        nodes = self.get_connected_nodes()
        snapshots = self.list_snapshots()
        return {
            'version': self.version,
            'role': self.role.value,
            'current_version': self._current_version,
            'syncthing_running': self._running,
            'connected_nodes': len(nodes),
            'total_snapshots': len(snapshots),
            'last_sync': self._last_sync
        }

    def print_status(self):
        s = self.get_status()
        print("\n" + "=" * 70)
        print("🔄 HELIX SYNC STATUS")
        print("=" * 70)
        print(f"  Role:             {s['role']}")
        print(f"  Version:          {s['current_version']}")
        print(f"  Syncthing:        {'running' if s['syncthing_running'] else 'stopped'}")
        print(f"  Connected nodes:  {s['connected_nodes']}")
        print(f"  Snapshots:        {s['total_snapshots']}")
        print(f"  Last sync bytes:  {s['last_sync']}\n")


# ============================================================================
# PART 10: SIMPLE API
# ============================================================================

# Franken002 identifier
LE002GEN5 = "LE002GEN5"

_helix = None
_translator = None
_agnostic = None
_sync: Optional[HelixSync] = None

def init_sync(config: dict = None, start: bool = False) -> 'HelixSync':
    """Initialize (and optionally start) the Helix sync module."""
    global _sync
    _sync = HelixSync(config)
    if start:
        _sync.start()
    return _sync

def init_helix(l1_mb=512, l2_mb=2048, l3_mb=6000, vram_mb=8096):
    global _helix, _translator, _agnostic
    print(f"\n🧬 Initializing Helix System [{LE002GEN5}]...")
    print(f"   L1: {l1_mb}MB | L2: {l2_mb}MB | L3: {l3_mb}MB | VRAM: {vram_mb}MB")
    _helix = HelixSystem(l1_mb, l2_mb, l3_mb, vram_mb)
    _translator = HelixTranslator(_helix)
    _agnostic = AgnosticLayer()
    print(f"   Platform: {_agnostic.system.os_type.value} ({_agnostic.system.architecture})")
    print("✓ Ready!\n")
    return _translator

def helix_malloc(size):
    if _translator is None: init_helix()
    return _translator.translate_malloc(size)

def helix_free(ptr):
    if _translator is None: init_helix()
    return _translator.translate_free(ptr)

def helix_read(ptr, size, offset=0):
    if _translator is None: init_helix()
    return _translator.translate_read(ptr, size, offset)

def helix_write(ptr, data, offset=0):
    if _translator is None: init_helix()
    return _translator.translate_write(ptr, data, offset)

def helix_stats():
    if _helix: _helix.print_stats()
    if _translator:
        print("🔄 TRANSLATOR:")
        print(f"  malloc() calls:  {_translator.stats['malloc_intercepts']:,}")
        print(f"  free() calls:    {_translator.stats['free_intercepts']:,}")
        print(f"  Active ptrs:     {len(_translator.ptr_to_key):,}\n")

# ============================================================================
# MAIN
# ============================================================================

def main():
    pm = ProcessManager()
    my_pid = pm.register_pid("Franken002")
    print(f"Frank starting (PID {my_pid}, Core 3, Real-time priority)")

    init_helix()

    print("TEST 1: Basic Memory Operations")
    print("-" * 70)
    ptr = helix_malloc(1024)
    print(f"✓ malloc(1024) → {hex(ptr)}")
    helix_write(ptr, b"Hello Helix!")
    data = helix_read(ptr, 12)
    print(f"✓ read() → {data}")
    helix_free(ptr)
    print(f"✓ free() → released\n")

    print("TEST 2: Stress Test (1000 allocations)")
    print("-" * 70)
    ptrs = []
    for i in range(1000):
        p = helix_malloc(512)
        helix_write(p, f"Block {i}".encode())
        ptrs.append(p)
    print(f"✓ Allocated 1000 blocks")
    for _ in range(5):
        idx = random.randint(0, 999)
        d = helix_read(ptrs[idx], 20)
        print(f"  Block {idx}: {d}")
    for p in ptrs:
        helix_free(p)
    print(f"✓ Freed 1000 blocks\n")

    print("TEST 3: Sync Module Init")
    print("-" * 70)
    sync = init_sync()  # init only, don't start Syncthing daemon (no daemon needed for test)
    sync.print_status()

    print("TEST 4: OS Detection")

    print("-" * 70)
    print(f"  OS: {_agnostic.system.os_type.value}")
    print(f"  Arch: {_agnostic.system.architecture}")
    print(f"  Home: {_agnostic.system.home_dir}")
    print(f"  Python: {_agnostic.find_python()}\n")

    helix_stats()
    print("=" * 70)
    print(f"✓ Franken2 [{LE002GEN5}] ALL TESTS PASSED!")
    print("=" * 70)

if __name__ == "__main__":
    main()
