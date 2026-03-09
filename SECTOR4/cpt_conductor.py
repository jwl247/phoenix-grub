#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  ⚓ CPT CONDUCTOR — SECTOR4                                                  ║
║                                                                              ║
║  Multi-conductor architecture with Helix translation                        ║
║                                                                              ║
║  Each coms ring gets its own conductor                                      ║
║  One peer conductor coordinates cross-ring routing                          ║
║  All conductors communicate via Helix translation pipeline                  ║
║  Intent-based routing to correct conductor                                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import json
import time
import signal
import threading
from pathlib import Path
from typing import Dict, Optional

# ============================================================================
# CONFIG
# ============================================================================

SECTOR          = "SECTOR4"
BASE_DIR        = Path("/etc/systemd/system/SECTOR4")
COMS_DIR        = BASE_DIR                          # coms1-4 live here
STORAGE_DIR     = Path("/etc/HEix7_3GIII/storage")  # persistent storage index
PEER_QUEUE      = Path("/etc/HEix7_3GIII/peer_queue")
PID_DIR         = Path("/etc/HEix7_3GIII/conductors")
CHIEF_DIR       = Path("/opt/chief")

STORAGE_DIR.mkdir(parents=True, exist_ok=True)
PEER_QUEUE.mkdir(parents=True, exist_ok=True)
PID_DIR.mkdir(parents=True, exist_ok=True)

# Coms rings and their storage segments
COMS_RINGS = {
    "coms1": 1,
    "coms2": 2,
    "coms3": 3,
    "coms4": 4,
}

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [CONDUCTOR] %(message)s',
    handlers=[logging.StreamHandler()]
)

# ============================================================================
# HELIX TRANSLATION — inline stub if pipeline not available
# ============================================================================

try:
    from helix_universal_translation import HelixTranslationPipeline
except ImportError:
    class HelixTranslationPipeline:
        """Stub when helix_universal_translation not yet available."""
        def ingest(self, data, source_format, key):
            return data
        def to_bytes(self, data):
            return json.dumps(data).encode()


# ============================================================================
# BASE CONDUCTOR
# ============================================================================

class BaseConductor:
    """
    Base conductor — handles coms routing and storage writes.
    Each conductor owns one coms ring.
    """

    def __init__(self, conductor_id: str, coms_id: str):
        self.conductor_id = conductor_id
        self.coms_id      = coms_id
        self.pipeline     = HelixTranslationPipeline()
        self.running      = False
        self.thread       = None
        self.pid          = os.getpid()
        self._register_pid()

    def _register_pid(self):
        pid_file = PID_DIR / f"{self.conductor_id}.pid"
        pid_file.write_text(str(self.pid))
        logging.info(f"Conductor {self.conductor_id} registered PID {self.pid}")

    def start(self):
        self.running = True
        self.thread  = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        logging.info(f"Conductor {self.conductor_id} started")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logging.info(f"Conductor {self.conductor_id} stopped")

    def run(self):
        raise NotImplementedError

    def process_message(self, msg_path: Path):
        raise NotImplementedError


# ============================================================================
# COMS CONDUCTOR — one per ring
# ============================================================================

class ComsConductor(BaseConductor):
    """
    Local coms conductor.
    Handles messages for its own coms ring.
    Translates incoming data via Helix pipeline.
    Routes to local storage segment.
    Forwards to peer conductor if cross-ring.
    """

    def __init__(self, coms_id: str, storage_segment: int):
        super().__init__(f"conductor_{coms_id}", coms_id)
        self.storage_segment = storage_segment
        self.watch_dir       = STORAGE_DIR / coms_id
        self.watch_dir.mkdir(parents=True, exist_ok=True)

    def run(self):
        logging.info(f"Conductor {self.coms_id} watching: {self.watch_dir}")
        while self.running:
            for msg_file in self.watch_dir.glob("*.json"):
                try:
                    self.process_message(msg_file)
                    msg_file.unlink()
                except Exception as e:
                    logging.error(f"Error processing {msg_file.name}: {e}")
            time.sleep(0.1)

    def process_message(self, msg_path: Path):
        with open(msg_path) as f:
            msg = json.load(f)

        msg_id        = msg.get('id', msg_path.stem)
        target_ring   = msg.get('target_ring', self.coms_id)

        logging.info(f"Coms {self.coms_id} processing: {msg_id}")

        if target_ring != self.coms_id:
            self._forward_to_peer(msg)
            return

        # Translate via Helix pipeline
        helix_value = self.pipeline.ingest(
            data          = msg,
            source_format = "json",
            key           = msg_id
        )

        self._write_to_storage(helix_value, msg_id)
        logging.info(f"Stored in storage segment {self.storage_segment}: {msg_id}")

    def _write_to_storage(self, data, msg_id: str):
        """Write translated data to this ring's storage segment."""
        storage_path = BASE_DIR / self.coms_id / "breach" / f"storage_{self.storage_segment}"
        storage_path.mkdir(parents=True, exist_ok=True)

        out = storage_path / f"{msg_id}.json"
        try:
            if isinstance(data, (dict, list)):
                out.write_text(json.dumps(data))
            elif isinstance(data, bytes):
                out.write_bytes(data)
            else:
                out.write_text(json.dumps({'data': str(data)}))
        except Exception as e:
            logging.error(f"Storage write error: {e}")

    def _forward_to_peer(self, msg: Dict):
        """Forward message to peer conductor for cross-ring routing."""
        peer_path = PEER_QUEUE / f"{msg.get('id', 'unknown')}_{int(time.time()*1000)}.json"
        peer_path.write_text(json.dumps(msg))
        logging.info(f"Forwarded to peer: {msg.get('id')}")


# ============================================================================
# PEER CONDUCTOR — single instance, cross-ring coordination
# ============================================================================

class PeerConductor(BaseConductor):
    """
    Peer coordination conductor.
    Single instance — coordinates between coms conductors.
    Handles cross-ring message routing.
    Discovers active conductors by PID.
    """

    def __init__(self):
        super().__init__("conductor_peer", "peer")
        self.active_conductors: Dict[str, Dict] = {}
        self._discover_conductors()

    def _discover_conductors(self):
        for pid_file in PID_DIR.glob("conductor_coms*.pid"):
            conductor_id = pid_file.stem
            try:
                pid = int(pid_file.read_text().strip())
                if self._is_running(pid):
                    coms_id = conductor_id.replace("conductor_", "")
                    self.active_conductors[coms_id] = {
                        'conductor_id': conductor_id,
                        'pid':          pid,
                        'status':       'active'
                    }
                    logging.info(f"Found conductor: {coms_id} PID {pid}")
            except:
                pass

    def _is_running(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def run(self):
        logging.info(f"Peer conductor watching: {PEER_QUEUE}")
        while self.running:
            for msg_file in PEER_QUEUE.glob("*.json"):
                try:
                    self.process_message(msg_file)
                    msg_file.unlink()
                except Exception as e:
                    logging.error(f"Peer error: {e}")
            time.sleep(0.05)  # Faster — peer needs to be responsive

    def process_message(self, msg_path: Path):
        with open(msg_path) as f:
            msg = json.load(f)

        target_ring = msg.get('target_ring')
        msg_id      = msg.get('id', msg_path.stem)

        if not target_ring:
            logging.warning(f"No target ring in message: {msg_id}")
            return

        logging.info(f"Peer routing {msg_id} → {target_ring}")

        # Route to target ring's storage directory
        target_dir = STORAGE_DIR / target_ring
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / msg_path.name).write_text(json.dumps(msg))

    def broadcast(self, msg: Dict):
        """Broadcast message to ALL coms rings."""
        msg_id = msg.get('id', f"broadcast_{int(time.time()*1000)}")
        logging.info(f"Broadcasting {msg_id} to all rings")
        for coms_id in COMS_RINGS:
            target_dir = STORAGE_DIR / coms_id
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / f"{msg_id}_{coms_id}.json").write_text(json.dumps(msg))


# ============================================================================
# CONDUCTOR MANAGER
# ============================================================================

class ConductorManager:
    """Manages all conductors in SECTOR4."""

    def __init__(self):
        self.coms_conductors: list = []
        self.peer_conductor:  Optional[PeerConductor] = None
        self.start_time = time.time()

    def setup(self):
        """Create conductors for all coms rings."""
        for coms_id, segment in COMS_RINGS.items():
            c = ComsConductor(coms_id, segment)
            self.coms_conductors.append(c)
            logging.info(f"Created conductor: {coms_id} → storage segment {segment}")

        self.peer_conductor = PeerConductor()
        logging.info("Created peer conductor")
        return self

    def start_all(self):
        for c in self.coms_conductors:
            c.start()
        if self.peer_conductor:
            self.peer_conductor.start()
        logging.info(f"All conductors started: {len(self.coms_conductors)} coms + 1 peer")

    def stop_all(self):
        if self.peer_conductor:
            self.peer_conductor.stop()
        for c in self.coms_conductors:
            c.stop()
        logging.info("All conductors stopped")

    def status(self):
        print()
        print("=" * 60)
        print(f"  CONDUCTOR STATUS — {SECTOR}")
        print("=" * 60)
        print(f"\n  COMS CONDUCTORS ({len(self.coms_conductors)}):")
        for c in self.coms_conductors:
            state = "RUNNING" if c.running else "STOPPED"
            print(f"    [{state}] {c.coms_id} → storage segment {c.storage_segment}")
        if self.peer_conductor:
            state = "RUNNING" if self.peer_conductor.running else "STOPPED"
            peers = len(self.peer_conductor.active_conductors)
            print(f"\n  PEER CONDUCTOR:")
            print(f"    [{state}] active coms conductors: {peers}")
        uptime = round(time.time() - self.start_time, 1)
        print(f"\n  Uptime: {uptime}s")
        print("=" * 60)
        print()

    def send_message(self, target_ring: str, msg_id: str, data: Dict):
        """Drop a message into a coms ring's storage directory."""
        msg = {'id': msg_id, 'target_ring': target_ring, 'data': data,
               'ts': time.time(), 'sector': SECTOR}
        target_dir = STORAGE_DIR / target_ring
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / f"{msg_id}.json").write_text(json.dumps(msg))
        logging.info(f"Message dropped → {target_ring}: {msg_id}")


# ============================================================================
# SIGNAL HANDLING
# ============================================================================

manager: Optional[ConductorManager] = None

def handle_signal(sig, frame):
    logging.info(f"Signal {sig} — shutting down")
    if manager: manager.stop_all()
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT,  handle_signal)


# ============================================================================
# CLI
# ============================================================================

def main():
    global manager

    usage = """
Commands:
  start        Start all conductors
  stop         Stop all conductors
  status       Show conductor status
  send <ring> <id> <data>   Send message to a coms ring
"""

    if len(sys.argv) < 2:
        print(usage); sys.exit(1)

    cmd = sys.argv[1].lower()
    manager = ConductorManager().setup()

    if cmd == 'start':
        manager.start_all()
        print(f"Conductors running. Ctrl+C to stop.")
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            manager.stop_all()

    elif cmd == 'status':
        manager.start_all()
        time.sleep(0.5)
        manager.status()
        manager.stop_all()

    elif cmd == 'send':
        if len(sys.argv) < 5:
            print("Usage: send <ring> <id> <json_data>"); sys.exit(1)
        ring = sys.argv[2]
        mid  = sys.argv[3]
        data = json.loads(sys.argv[4])
        manager.send_message(ring, mid, data)
        print(f"Message sent → {ring}: {mid}")

    else:
        print(f"Unknown: {cmd}"); print(usage)


if __name__ == "__main__":
    main()
