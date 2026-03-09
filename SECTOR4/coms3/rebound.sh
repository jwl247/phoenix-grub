#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  🔄 REBOUND — Ring Watchdog & Auto-Recovery                                  ║
║     SECTOR4 / coms4                                                          ║
║                                                                              ║
║  Watches all ring processes. Detects offline. Restarts clean.                ║
║  Circuit breaker: 3 strikes → hold + signal up chain.                       ║
║  Reports to guardian BEFORE restart not after.                               ║
║  Logs everything to breach/ directory.                                       ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import time
import json
import signal
import logging
import threading
import subprocess
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Optional, List
from collections import defaultdict

# ============================================================================
# CONFIG
# ============================================================================

RING_DIR     = Path(__file__).parent
BREACH_DIR   = RING_DIR / "breach"
GUARDIAN_LOG = RING_DIR / "file_guardian.json"
LOG_FILE     = BREACH_DIR / "rebound.log"

# Processes to watch — name: entry point
WATCH_TARGETS = {
    "franken":           RING_DIR / "franken.py",
    "integrated_guardian": RING_DIR / "integrated_guardian.py",
    "freewheeling":      RING_DIR / "freewheeling.py",
    "conductor_sync":    RING_DIR / "conductor_sync.py",
    "propcoms":          RING_DIR / "propcoms.py",
    "quadengine":        RING_DIR / "quadengine.py",
    "helix_api":         RING_DIR / "helix_api.py",
}

# Rebound behavior
MAX_STRIKES       = 3       # failures before circuit breaker trips
RESTART_DELAY     = 3.0     # seconds before restart attempt
STRIKE_RESET_SEC  = 300     # seconds of clean uptime resets strike count
WATCH_INTERVAL    = 5.0     # seconds between health checks
BREACH_HOLD_SEC   = 60      # seconds to hold after circuit breaker trip

# ============================================================================
# LOGGING
# ============================================================================

BREACH_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [REBOUND] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

# ============================================================================
# PROCESS STATE
# ============================================================================

@dataclass
class ProcessState:
    name:         str
    script:       Path
    pid:          Optional[int]  = None
    process:      Optional[subprocess.Popen] = None
    strikes:      int            = 0
    tripped:      bool           = False
    trip_time:    Optional[float]= None
    last_start:   Optional[float]= None
    last_healthy: Optional[float]= None
    total_restarts: int          = 0
    total_trips:  int            = 0

    def is_alive(self) -> bool:
        if self.process is None:
            return False
        return self.process.poll() is None

    def uptime(self) -> float:
        if self.last_start is None:
            return 0.0
        return time.time() - self.last_start

    def to_dict(self) -> Dict:
        return {
            'name':            self.name,
            'pid':             self.pid,
            'alive':           self.is_alive(),
            'strikes':         self.strikes,
            'tripped':         self.tripped,
            'uptime_sec':      round(self.uptime(), 1),
            'total_restarts':  self.total_restarts,
            'total_trips':     self.total_trips,
            'last_start':      str(datetime.fromtimestamp(self.last_start))
                               if self.last_start else None,
        }


# ============================================================================
# GUARDIAN NOTIFICATION
# ============================================================================

def notify_guardian(event: str, name: str, detail: str = ""):
    """
    Write rebound events to the guardian log so the guardian
    knows what's happening before we act.
    """
    try:
        existing = {}
        if GUARDIAN_LOG.exists():
            try:
                existing = json.loads(GUARDIAN_LOG.read_text())
            except:
                existing = {}

        rebound_log = existing.get("rebound_events", [])
        rebound_log.append({
            "timestamp": str(datetime.now()),
            "event":     event,
            "process":   name,
            "detail":    detail,
            "sector":    "SECTOR4",
            "ring":      "coms4"
        })

        # Keep last 100 events
        existing["rebound_events"] = rebound_log[-100:]
        existing["rebound_last_event"] = {
            "timestamp": str(datetime.now()),
            "event": event,
            "process": name
        }

        GUARDIAN_LOG.write_text(json.dumps(existing, indent=2))

    except Exception as e:
        logging.warning(f"Guardian notify failed: {e}")


def write_breach(name: str, strikes: int, reason: str):
    """Write breach report to breach/ directory."""
    try:
        ts   = datetime.now().strftime("%Y%m%dT%H%M%S")
        path = BREACH_DIR / f"breach_{name}_{ts}.json"
        path.write_text(json.dumps({
            "timestamp": str(datetime.now()),
            "process":   name,
            "strikes":   strikes,
            "reason":    reason,
            "sector":    "SECTOR4",
            "ring":      "coms4"
        }, indent=2))
    except Exception as e:
        logging.warning(f"Breach write failed: {e}")


# ============================================================================
# REBOUND ENGINE
# ============================================================================

class ReboundEngine:
    def __init__(self):
        self.states: Dict[str, ProcessState] = {}
        self.lock    = threading.Lock()
        self.running = False

        for name, script in WATCH_TARGETS.items():
            self.states[name] = ProcessState(name=name, script=script)

    # ── Start a process ──────────────────────────────────────────────────────

    def _start(self, state: ProcessState) -> bool:
        if not state.script.exists():
            logging.warning(f"[{state.name}] Script not found: {state.script}")
            return False

        try:
            proc = subprocess.Popen(
                [sys.executable, str(state.script)],
                cwd=str(RING_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                start_new_session=True
            )
            state.process    = proc
            state.pid        = proc.pid
            state.last_start = time.time()
            logging.info(f"[{state.name}] Started PID {proc.pid}")
            return True

        except Exception as e:
            logging.error(f"[{state.name}] Start failed: {e}")
            return False

    # ── Check one process ─────────────────────────────────────────────────────

    def _check(self, state: ProcessState):
        alive = state.is_alive()

        # Still running — check for strike reset
        if alive:
            state.last_healthy = time.time()
            if (state.strikes > 0
                    and state.uptime() > STRIKE_RESET_SEC):
                logging.info(f"[{state.name}] Clean uptime — strikes reset")
                state.strikes = 0
                state.tripped = False
            return

        # ── Process is down ──────────────────────────────────────────────────

        # First time we see it — just start it
        if state.last_start is None:
            logging.info(f"[{state.name}] Initial start")
            notify_guardian("initial_start", state.name)
            self._start(state)
            return

        # Circuit breaker already tripped — hold
        if state.tripped:
            held = time.time() - (state.trip_time or time.time())
            if held < BREACH_HOLD_SEC:
                logging.warning(f"[{state.name}] TRIPPED — holding "
                                f"({BREACH_HOLD_SEC - held:.0f}s remaining)")
                return
            else:
                # Hold period over — one more attempt then re-trip if needed
                logging.info(f"[{state.name}] Hold period over — attempting recovery")
                state.tripped = False
                state.strikes = MAX_STRIKES - 1  # one more chance

        state.strikes += 1
        logging.warning(f"[{state.name}] OFFLINE — strike {state.strikes}/{MAX_STRIKES}")

        # Notify guardian BEFORE we act
        notify_guardian("process_offline", state.name,
                        f"strike {state.strikes}/{MAX_STRIKES}")

        # Circuit breaker
        if state.strikes >= MAX_STRIKES:
            state.tripped   = True
            state.trip_time = time.time()
            state.total_trips += 1
            logging.critical(
                f"[{state.name}] CIRCUIT BREAKER TRIPPED after "
                f"{MAX_STRIKES} strikes — holding {BREACH_HOLD_SEC}s")
            notify_guardian("circuit_breaker_trip", state.name,
                            f"holding {BREACH_HOLD_SEC}s — manual review needed")
            write_breach(state.name, state.strikes, "circuit_breaker_trip")
            return

        # Restart
        logging.info(f"[{state.name}] Rebooting in {RESTART_DELAY}s...")
        time.sleep(RESTART_DELAY)

        notify_guardian("restarting", state.name,
                        f"attempt {state.strikes}")

        ok = self._start(state)
        if ok:
            state.total_restarts += 1
            logging.info(f"[{state.name}] ✓ Rebound — "
                         f"total restarts: {state.total_restarts}")
            notify_guardian("rebound_success", state.name,
                            f"PID {state.pid}")
        else:
            logging.error(f"[{state.name}] Rebound FAILED")
            notify_guardian("rebound_failed", state.name, "start error")
            write_breach(state.name, state.strikes, "rebound_failed")

    # ── Main watch loop ───────────────────────────────────────────────────────

    def run(self):
        self.running = True
        logging.info("=" * 60)
        logging.info("  🔄 REBOUND watchdog starting")
        logging.info(f"  Ring:    {RING_DIR}")
        logging.info(f"  Watching {len(self.states)} processes")
        logging.info(f"  Interval: {WATCH_INTERVAL}s  "
                     f"Max strikes: {MAX_STRIKES}  "
                     f"Hold: {BREACH_HOLD_SEC}s")
        logging.info("=" * 60)

        notify_guardian("watchdog_start", "rebound",
                        f"watching {len(self.states)} processes")

        while self.running:
            with self.lock:
                for state in self.states.values():
                    try:
                        self._check(state)
                    except Exception as e:
                        logging.error(f"[{state.name}] check error: {e}")

            # Status summary every 60s
            if int(time.time()) % 60 < WATCH_INTERVAL:
                self._status_summary()

            time.sleep(WATCH_INTERVAL)

    def _status_summary(self):
        with self.lock:
            alive   = sum(1 for s in self.states.values() if s.is_alive())
            tripped = sum(1 for s in self.states.values() if s.tripped)
            total_r = sum(s.total_restarts for s in self.states.values())
            logging.info(
                f"STATUS  alive:{alive}/{len(self.states)}  "
                f"tripped:{tripped}  total_restarts:{total_r}")

    def stop(self):
        self.running = False
        notify_guardian("watchdog_stop", "rebound", "clean shutdown")
        logging.info("[REBOUND] Stopped")

    def get_status(self) -> Dict:
        with self.lock:
            return {
                'ring':      'coms4',
                'sector':    'SECTOR4',
                'timestamp': str(datetime.now()),
                'processes': {n: s.to_dict() for n, s in self.states.items()},
                'summary': {
                    'total':    len(self.states),
                    'alive':    sum(1 for s in self.states.values() if s.is_alive()),
                    'tripped':  sum(1 for s in self.states.values() if s.tripped),
                    'restarts': sum(s.total_restarts for s in self.states.values()),
                }
            }


# ============================================================================
# SIGNAL HANDLING
# ============================================================================

engine: Optional[ReboundEngine] = None

def handle_signal(sig, frame):
    logging.info(f"[REBOUND] Signal {sig} received — shutting down")
    if engine:
        engine.stop()
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT,  handle_signal)


# ============================================================================
# CLI
# ============================================================================

def main():
    global engine

    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()

        if cmd == 'status':
            e = ReboundEngine()
            print(json.dumps(e.get_status(), indent=2))
            return

        elif cmd == 'check':
            # One-shot check — useful for testing
            e = ReboundEngine()
            for name, state in e.states.items():
                exists = state.script.exists()
                print(f"  {'✓' if exists else '✗'} {name:<25} {state.script}")
            return

        elif cmd == 'breach':
            # Show breach log
            files = sorted(BREACH_DIR.glob("breach_*.json"))
            if not files:
                print("No breach reports.")
                return
            for f in files[-10:]:  # last 10
                try:
                    print(json.dumps(json.loads(f.read_text()), indent=2))
                    print()
                except:
                    pass
            return

    # Default: run watchdog
    engine = ReboundEngine()
    try:
        engine.run()
    except KeyboardInterrupt:
        pass
    finally:
        if engine:
            engine.stop()


if __name__ == "__main__":
    main()
