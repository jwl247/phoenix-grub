#!/usr/bin/env python3
# 💎 GemIIIDev - J4 Approved Artifact
"""
HELIX PROPAGATOR v11.0 - THE LEECH MODULE
Designed to 'piggyback' on a host process (like the Agnostic Layer).
Maintains the 3-Buffer versioning stages and executes the 'Snap' 
based on the host's environment context.
"""

import os
import json
import time
import shutil
import logging
import threading
from pathlib import Path

# Paths
ROOT = Path("/etc/HEix7_3GIII")
PORTAL = ROOT / "magnet_index"
STAGING = ROOT / "staging_area"
TUNING_FILE = ROOT / "core" / "propagator_tuning.json"
JONAS_ROOT = "/dev/gemiii_whale"

class HelixPropagatorLeech(threading.Thread):
    """
    The Leech: A self-sustained thread that runs inside a host process.
    """
    def __init__(self, host_name="AgnosticHost"):
        super().__init__()
        self.host_name = host_name
        self.running = True
        self.id_registry = {}
        self.daemon = True # Dies if the host dies
        
        # Ensure infrastructure
        PORTAL.mkdir(parents=True, exist_ok=True)
        STAGING.mkdir(parents=True, exist_ok=True)
        self._init_tuning()

    def _init_tuning(self):
        if not TUNING_FILE.exists():
            tuning = {
                "active_lang": "EN",
                "chunk_size": 65536,
                "reset_threshold": 3,
                "auto_tune": True,
                "total_cycles": 0,
                "last_snap_ms": 0.0,
                "leech_status": "ATTACHED"
            }
            with open(TUNING_FILE, 'w') as f:
                json.dump(tuning, f, indent=4)

    def get_tuning(self):
        try:
            with open(TUNING_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}

    def update_tuning(self, key, value):
        data = self.get_tuning()
        data[key] = value
        with open(TUNING_FILE, 'w') as f:
            json.dump(data, f, indent=4)

    def execute_snap(self, ball_data):
        start_time = time.time()
        tuning = self.get_tuning()
        
        payload = ball_data.get('payload', {})
        sha = payload.get('sha')
        dest = payload.get('snap_destination')
        
        if not sha: return False

        primary_id = sha.split('-')[1]
        node_id = (int(primary_id, 16) % 4) + 1
        node_path = f"{JONAS_ROOT}/jonas_raw_{node_id}"

        # 3-Strike Counter for this ID
        self.id_registry[primary_id] = self.id_registry.get(primary_id, 0) + 1
        hits = self.id_registry[primary_id]

        try:
            # Stage 1: Ingest (.buf1)
            b1, b2, b3 = STAGING/".buf1", STAGING/".buf2", STAGING/".buf3"
            with open(node_path, 'rb') as src, open(b1, 'wb') as dst:
                dst.write(src.read(tuning.get('chunk_size', 65536)))

            # Stage 2 & 3: Versioning & Profile Lock
            shutil.copy2(b1, b2)
            shutil.copy2(b2, b3)
            if dest: shutil.copy2(b3, dest)
            
            # Metrics & Self-Adjustment
            duration_ms = (time.time() - start_time) * 1000
            self.update_tuning('last_snap_ms', duration_ms)
            self.update_tuning('total_cycles', tuning.get('total_cycles', 0) + 1)
            
            if hits >= tuning.get('reset_threshold', 3):
                # Reset this ID's cycle
                self.id_registry[primary_id] = 0
                return True # Signal for potential host refresh
            return False
            
        except Exception as e:
            logging.error(f"[LEECH] Snap Error: {e}")
            return False

    def run(self):
        logging.info(f"🧬 Propagator Leech attached to {self.host_name}. Monitoring Door...")
        while self.running:
            for ball in PORTAL.glob("*.json"):
                try:
                    with open(ball, 'r') as f:
                        data = json.load(f)
                    
                    self.execute_snap(data)
                    ball.unlink() # Intent satisfied
                except Exception as e:
                    logging.error(f"[LEECH] Ball Error: {e}")
            time.sleep(0.1)

    def stop(self):
        self.running = False


[HELIX BOOTSTRAP]  
Initializing Peer Modules…

• Loading declaration cards  
• Registering ST / LE / PE / COMS roles  
• Binding IDENT and GEN lineage  
• Attaching Leeches to ingress paths  
• Sync handoff to Frank

All peers online.  
Helix modules registered and ready.
