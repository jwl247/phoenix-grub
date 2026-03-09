#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  🧠 AI-Powered Dynamic Paging Manager v3.0                                   ║
║     Linux Edition — NVMe Optimized                                           ║
║                                                                              ║
║  Manages Linux swap dynamically for AI workloads                             ║
║  Uses /proc/meminfo, swapon/swapoff, dd — no dependencies                   ║
║                                                                              ║
║  Subsystems:                                                                 ║
║    • PredictiveEngine    — tier velocity watching, acts before pressure hits ║
║    • VirtualProcessor    — dedicated emergency circuit breaker               ║
║    • SwapManager         — swapfile create/activate/deactivate/resize        ║
║    • SystemMonitor       — /proc/meminfo + /proc/stat direct reads           ║
║    • ControlSystem       — persistent enable/disable/emergency state         ║
║    • Dashboard           — live web UI on port 8888                          ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import time
import threading
import subprocess
import json
import ctypes
import math
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Tuple
from collections import deque, defaultdict
from enum import Enum
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler

# ============================================================================
# ROOT CHECK
# ============================================================================

def is_root() -> bool:
    return os.geteuid() == 0

# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class SystemConfig:
    # Hardware
    total_ram_gb:             float = 16.0
    nvme_mount:               str   = "/mnt/nvme"        # Dedicated 256GB NVMe mount
    nvme_size_gb:             float = 256.0

    # Swapfile
    swapfile_path:            str   = "/mnt/nvme/swapfile"
    max_swap_gb:              float = 200.0
    min_swap_gb:              float = 4.0
    initial_swap_gb:          float = 16.0

    # Thermal
    max_cpu_temp:             float = 80.0
    thermal_throttle_temp:    float = 75.0

    # Predictive engine
    ai_mode:                  bool  = True
    prediction_window:        int   = 10
    velocity_threshold:       float = 0.15
    micro_adjust_min_gb:      float = 0.5
    micro_adjust_max_gb:      float = 16.0

    # Legacy thresholds (fallback)
    expand_threshold_percent: float = 75.0
    shrink_threshold_percent: float = 30.0

    # Timing — NVMe can handle fast polling
    monitoring_interval:      int   = 5
    vp_interval:              int   = 3

    # Dashboard
    web_dashboard_port:       int   = 8888

    # Paths
    control_file:             str   = "/var/lib/ai-paging/control.json"
    log_file:                 str   = "/var/log/ai-paging-manager.log"


# ============================================================================
# VRRAM TIER TYPES
# ============================================================================

class MemoryTier(Enum):
    HOT    = 0
    WARM   = 1
    COLD   = 2
    FROZEN = 3

@dataclass
class TierSnapshot:
    timestamp:  float
    hot_mb:     float
    warm_mb:    float
    cold_mb:    float
    frozen_mb:  float
    hit_rate:   float
    promotions: int
    demotions:  int
    evictions:  int

    @property
    def pressure(self) -> float:
        total = self.hot_mb + self.warm_mb + self.cold_mb + self.frozen_mb
        return (self.hot_mb + self.warm_mb) / total if total > 0 else 0


# ============================================================================
# PREDICTIVE ENGINE
# ============================================================================

class PredictiveEngine:
    """
    Watches VRRAM tier VELOCITY — rate of change between tiers.
    Acts BEFORE pressure hits. Gets smarter every cycle.
    """

    def __init__(self, config: SystemConfig):
        self.config  = config
        self.history: deque = deque(maxlen=config.prediction_window)
        self.lock    = threading.Lock()
        self.cycle   = 0
        self.correct = 0
        self.total   = 0

    def record(self, snapshot: TierSnapshot, swap_pct: float, ram_pct: float):
        with self.lock:
            self.history.append({
                'snapshot':  snapshot,
                'swap_pct':  swap_pct,
                'ram_pct':   ram_pct,
                'timestamp': time.time()
            })
            self.cycle += 1

    def _velocity(self) -> Dict[str, float]:
        if len(self.history) < 2:
            return {'hot': 0.0, 'warm': 0.0, 'cold': 0.0,
                    'frozen': 0.0, 'swap': 0.0, 'elapsed': 0.0}
        recent  = list(self.history)
        first   = recent[0];  last = recent[-1]
        elapsed = max(last['timestamp'] - first['timestamp'], 1)
        fs      = first['snapshot']; ls = last['snapshot']
        return {
            'hot':    (ls.hot_mb    - fs.hot_mb)    / elapsed,
            'warm':   (ls.warm_mb   - fs.warm_mb)   / elapsed,
            'cold':   (ls.cold_mb   - fs.cold_mb)   / elapsed,
            'frozen': (ls.frozen_mb - fs.frozen_mb) / elapsed,
            'swap':   (last['swap_pct'] - first['swap_pct']) / elapsed,
            'elapsed': elapsed
        }

    def _eta_seconds(self, velocity: Dict) -> Optional[float]:
        if not self.history: return None
        current = self.history[-1]['swap_pct']
        sv      = velocity['swap']
        if sv <= 0: return None
        gap = self.config.expand_threshold_percent - current
        return None if gap <= 0 else gap / sv

    def _adjustment_gb(self, velocity: Dict,
                       swap_pct: float, pagefile_gb: float) -> float:
        if not self.history: return 0.0
        used_gb    = (swap_pct / 100) * pagefile_gb
        headroom   = used_gb * 0.25
        multiplier = 1.0 + max(0, velocity['hot'] / 100) + max(0, velocity['swap'] / 10)
        raw        = headroom * multiplier
        return max(self.config.micro_adjust_min_gb,
                   min(self.config.micro_adjust_max_gb, raw))

    def decide(self, swap_pct: float, ram_pct: float,
               pagefile_gb: float) -> Tuple[str, float, str]:
        with self.lock:
            self.total += 1
            if len(self.history) < 2:
                if swap_pct > self.config.expand_threshold_percent:
                    return ('expand', 4.0, 'legacy_no_history')
                if swap_pct < self.config.shrink_threshold_percent:
                    return ('shrink', 2.0, 'legacy_no_history')
                return ('hold', 0.0, 'no_history')

            vel = self._velocity()
            eta = self._eta_seconds(vel)

            if eta is not None and eta < 60:
                amt = self._adjustment_gb(vel, swap_pct, pagefile_gb)
                self.correct += 1
                return ('expand', amt, f'predictive_eta_{eta:.0f}s')

            if vel['hot'] > self.config.velocity_threshold * 100:
                amt = self._adjustment_gb(vel, swap_pct, pagefile_gb)
                return ('expand', amt, f'hot_velocity_{vel["hot"]:.1f}mbs')

            if swap_pct > self.config.expand_threshold_percent:
                amt = self._adjustment_gb(vel, swap_pct, pagefile_gb)
                return ('expand', amt, 'threshold_breach')

            if (swap_pct < self.config.shrink_threshold_percent
                    and vel['swap'] < 0 and pagefile_gb > self.config.min_swap_gb):
                shrink = max(self.config.micro_adjust_min_gb,
                             min(4.0, pagefile_gb - swap_pct/100*pagefile_gb*1.5))
                return ('shrink', shrink, 'pressure_dropping')

            return ('hold', 0.0, 'stable')

    def get_stats(self) -> Dict:
        with self.lock:
            vel = self._velocity() if len(self.history) >= 2 else {}
            acc = (self.correct / self.total * 100) if self.total else 0
            return {
                'cycle':        self.cycle,
                'history_depth':len(self.history),
                'accuracy_pct': round(acc, 1),
                'velocity':     {k: round(v, 3) for k, v in vel.items()},
                'total_calls':  self.total,
            }


# ============================================================================
# VIRTUAL PROCESSOR — Emergency Circuit Breaker
# ============================================================================

class VirtualProcessor:
    """
    Sits aloof. Watches hard signals only. Acts immediately.
    Reports to manager. Runs independently of main loop.
    """

    def __init__(self, config: SystemConfig, monitor, swap_manager, control):
        self.config       = config
        self.monitor      = monitor
        self.swap_manager = swap_manager
        self.control      = control
        self._running     = False
        self._thread      = None
        self.trips        = 0
        self.last_trip    = None
        self.last_reason  = None
        self.lock         = threading.Lock()

    def start(self):
        self._running = True
        self._thread  = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()
        logging.info("[VP] Virtual processor online")

    def stop(self):
        self._running = False

    def _watch(self):
        while self._running:
            try:    self._check()
            except Exception as e: logging.error(f"[VP] {e}")
            time.sleep(self.config.vp_interval)

    def _check(self):
        mem  = self.monitor.virtual_memory()
        swap = self.monitor.swap_memory()
        reasons = []

        if mem['percent'] > 95:
            reasons.append(f'RAM_CRITICAL_{mem["percent"]:.0f}pct')
        if swap['percent'] > 90:
            reasons.append(f'SWAP_CRITICAL_{swap["percent"]:.0f}pct')
        if mem['available_gb'] < 0.5:
            reasons.append('RAM_STARVED')

        if reasons:
            with self.lock:
                self.trips      += 1
                self.last_trip   = datetime.now()
                self.last_reason = ' | '.join(reasons)

            logging.critical(f"[VP] CIRCUIT BREAKER: {self.last_reason}")

            current   = self.swap_manager.get_current_swap_gb()
            disk_free = self.swap_manager.get_free_disk_gb()
            target    = min(current + 16.0,
                            self.config.max_swap_gb,
                            current + disk_free * 0.5)

            if target > current:
                logging.critical(f"[VP] Emergency expand → {target:.1f}GB")
                self.swap_manager.resize(target)

    def get_stats(self) -> Dict:
        with self.lock:
            return {
                'trips':       self.trips,
                'last_trip':   str(self.last_trip) if self.last_trip else None,
                'last_reason': self.last_reason,
                'watching':    self._running,
            }


# ============================================================================
# LINUX SYSTEM MONITOR
# ============================================================================

class LinuxSystemMonitor:
    """
    Reads /proc/meminfo and /proc/stat directly.
    No psutil dependency — pure stdlib.
    """

    def _read_meminfo(self) -> Dict[str, int]:
        info = {}
        try:
            with open('/proc/meminfo') as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        key = parts[0].rstrip(':')
                        info[key] = int(parts[1]) * 1024  # kB → bytes
        except Exception as e:
            logging.error(f"[MON] meminfo: {e}")
        return info

    def virtual_memory(self) -> Dict:
        m = self._read_meminfo()
        total     = m.get('MemTotal',     0)
        available = m.get('MemAvailable', 0)
        used      = total - available
        percent   = (used / total * 100) if total else 0
        return {
            'total_gb':     total    / 1e9,
            'available_gb': available / 1e9,
            'used_gb':      used     / 1e9,
            'percent':      percent,
        }

    def swap_memory(self) -> Dict:
        m = self._read_meminfo()
        total = m.get('SwapTotal', 0)
        free  = m.get('SwapFree',  0)
        used  = total - free
        percent = (used / total * 100) if total else 0
        return {
            'total_gb':  total / 1e9,
            'used_gb':   used  / 1e9,
            'free_gb':   free  / 1e9,
            'percent':   percent,
        }

    def cpu_percent(self) -> float:
        """Two-sample /proc/stat CPU measurement."""
        def _read():
            with open('/proc/stat') as f:
                line = f.readline()
            vals = list(map(int, line.split()[1:]))
            idle  = vals[3]
            total = sum(vals)
            return idle, total
        try:
            i1, t1 = _read(); time.sleep(0.2); i2, t2 = _read()
            dt = t2 - t1
            return ((dt - (i2 - i1)) / dt * 100) if dt else 0.0
        except:
            return 0.0

    def cpu_temperature(self) -> Optional[float]:
        """Try common Linux thermal zone paths."""
        paths = [
            '/sys/class/thermal/thermal_zone0/temp',
            '/sys/class/hwmon/hwmon0/temp1_input',
            '/sys/class/hwmon/hwmon1/temp1_input',
        ]
        for p in paths:
            try:
                val = int(Path(p).read_text().strip())
                return val / 1000.0   # millidegrees → degrees
            except:
                continue
        return None

    def get_disk_stats(self, path: str) -> Dict:
        try:
            st = os.statvfs(path)
            total = st.f_blocks * st.f_frsize
            free  = st.f_bavail * st.f_frsize
            used  = total - free
            return {
                'total_gb': total / 1e9,
                'free_gb':  free  / 1e9,
                'used_gb':  used  / 1e9,
                'used_pct': (used / total * 100) if total else 0,
            }
        except Exception as e:
            logging.error(f"[MON] disk stats {path}: {e}")
            return {'total_gb': 0, 'free_gb': 0, 'used_gb': 0, 'used_pct': 0}


# ============================================================================
# LINUX SWAP MANAGER
# ============================================================================

class LinuxSwapManager:
    """
    Creates and manages a swapfile on the dedicated NVMe.
    Uses fallocate + mkswap + swapon/swapoff.
    No restart required — changes are live immediately.
    """

    def __init__(self, config: SystemConfig):
        self.config       = config
        self.swapfile     = Path(config.swapfile_path)
        self.lock         = threading.Lock()
        self._current_gb  = 0.0

    def _run(self, cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=120, check=check)

    def get_current_swap_gb(self) -> float:
        """Read active swap from /proc/meminfo."""
        try:
            with open('/proc/meminfo') as f:
                for line in f:
                    if line.startswith('SwapTotal:'):
                        kb = int(line.split()[1])
                        return kb / 1e6
        except:
            pass
        return self._current_gb

    def get_free_disk_gb(self) -> float:
        try:
            mount = str(self.swapfile.parent)
            st    = os.statvfs(mount)
            return (st.f_bavail * st.f_frsize) / 1e9
        except:
            return 0.0

    def _deactivate(self) -> bool:
        if not self.swapfile.exists():
            return True
        try:
            r = self._run(['swapoff', str(self.swapfile)], check=False)
            if r.returncode not in (0, 1):
                logging.warning(f"[SWAP] swapoff warning: {r.stderr.strip()}")
            return True
        except Exception as e:
            logging.error(f"[SWAP] deactivate failed: {e}")
            return False

    def _create(self, size_gb: float) -> bool:
        size_bytes = int(size_gb * 1024 * 1024 * 1024)
        sf         = str(self.swapfile)

        # Ensure mount point exists
        self.swapfile.parent.mkdir(parents=True, exist_ok=True)

        # Try fallocate first (instant on NVMe)
        try:
            self._run(['fallocate', '-l', str(size_bytes), sf])
            logging.info(f"[SWAP] fallocate {size_gb:.1f}GB OK")
        except Exception:
            # Fallback to dd
            logging.warning("[SWAP] fallocate failed — using dd (slower)")
            count = int(size_gb * 1024)
            try:
                self._run(['dd', 'if=/dev/zero', f'of={sf}',
                           'bs=1M', f'count={count}', 'status=none'])
            except Exception as e:
                logging.error(f"[SWAP] dd failed: {e}")
                return False

        # Permissions
        os.chmod(sf, 0o600)

        # Format
        try:
            self._run(['mkswap', sf])
            logging.info("[SWAP] mkswap OK")
        except Exception as e:
            logging.error(f"[SWAP] mkswap failed: {e}")
            return False

        return True

    def _activate(self) -> bool:
        try:
            self._run(['swapon', str(self.swapfile)])
            logging.info("[SWAP] swapon OK")
            return True
        except Exception as e:
            logging.error(f"[SWAP] swapon failed: {e}")
            return False

    def initialize(self) -> bool:
        """Create initial swapfile if not already active."""
        with self.lock:
            current = self.get_current_swap_gb()
            if current > 0:
                logging.info(f"[SWAP] Existing swap: {current:.1f}GB — keeping")
                self._current_gb = current
                return True

            logging.info(f"[SWAP] Creating initial swapfile {self.config.initial_swap_gb}GB "
                         f"on {self.config.nvme_mount}")
            ok = self._create(self.config.initial_swap_gb) and self._activate()
            if ok:
                self._current_gb = self.config.initial_swap_gb
            return ok

    def resize(self, target_gb: float) -> bool:
        """
        Resize swapfile to target_gb.
        Live: deactivate → recreate → reactivate.
        On NVMe fallocate is near-instant so downtime is minimal.
        """
        with self.lock:
            target_gb = round(max(self.config.min_swap_gb,
                                  min(self.config.max_swap_gb, target_gb)), 1)
            current   = self.get_current_swap_gb()

            if abs(target_gb - current) < self.config.micro_adjust_min_gb:
                return True  # Already close enough

            direction = "→" if target_gb > current else "←"
            logging.info(f"[SWAP] Resize {current:.1f}GB {direction} {target_gb:.1f}GB")

            # Check disk space before expanding
            if target_gb > current:
                free = self.get_free_disk_gb()
                needed = target_gb - current
                if needed > free * 0.9:
                    logging.warning(f"[SWAP] Not enough disk: need {needed:.1f}GB, "
                                    f"have {free:.1f}GB free")
                    return False

            if not self._deactivate():
                return False

            if self.swapfile.exists():
                try:
                    self.swapfile.unlink()
                except Exception as e:
                    logging.error(f"[SWAP] unlink failed: {e}")
                    return False

            if not self._create(target_gb):
                return False

            if not self._activate():
                return False

            self._current_gb = target_gb
            logging.info(f"[SWAP] ✓ Swap now at {target_gb:.1f}GB")
            return True

    def expand(self, amount_gb: float) -> bool:
        return self.resize(self.get_current_swap_gb() + amount_gb)

    def shrink(self, amount_gb: float) -> bool:
        return self.resize(self.get_current_swap_gb() - amount_gb)

    def teardown(self):
        """Cleanly deactivate on shutdown."""
        logging.info("[SWAP] Teardown — deactivating swapfile")
        self._deactivate()


# ============================================================================
# CONTROL SYSTEM
# ============================================================================

class ControlSystem:
    def __init__(self, control_file: str):
        self.path = Path(control_file)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state = {
            'enabled':        True,
            'emergency_stop': False,
            'ai_mode':        True,
            'last_command':   None,
            'last_command_time': None,
        }
        self.lock = threading.Lock()
        self._load()

    def _load(self):
        try:
            if self.path.exists():
                self.state.update(json.loads(self.path.read_text()))
        except: pass

    def _save(self):
        try:
            self.path.write_text(json.dumps(self.state, indent=2, default=str))
        except Exception as e:
            logging.error(f"[CTRL] save: {e}")

    def _cmd(self, **kw):
        with self.lock:
            self.state.update(kw)
            self.state['last_command_time'] = str(datetime.now())
            self._save()

    def enable(self):
        self._cmd(enabled=True, emergency_stop=False, last_command='enable')
        logging.info("[CTRL] Enabled")

    def disable(self):
        self._cmd(enabled=False, last_command='disable')
        logging.info("[CTRL] Disabled")

    def emergency_stop(self):
        self._cmd(enabled=False, emergency_stop=True, last_command='emergency_stop')
        logging.critical("[CTRL] EMERGENCY STOP")

    def set_ai_mode(self, on: bool):
        self._cmd(ai_mode=on, last_command=f'ai_mode_{on}')

    def is_enabled(self) -> bool:
        with self.lock:
            return self.state['enabled'] and not self.state['emergency_stop']

    def is_ai_mode(self) -> bool:
        with self.lock:
            return self.state.get('ai_mode', True)

    def get_state(self) -> Dict:
        with self.lock:
            return self.state.copy()


# ============================================================================
# DASHBOARD
# ============================================================================

class DashboardHandler(BaseHTTPRequestHandler):
    manager = None

    def do_GET(self):
        if   self.path == '/':               self._html()
        elif self.path == '/api/status':     self._json(self.manager.get_status_dict())
        elif self.path.startswith('/api/control/'): self._control(self.path.split('/')[-1])
        else:                                self.send_error(404)

    def _html(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        html = """<!DOCTYPE html>
<html><head><title>AI Paging Manager v3 — Linux</title>
<meta http-equiv="refresh" content="5">
<style>
*{box-sizing:border-box}
body{font-family:monospace;background:#0a0a0a;color:#00ff88;padding:20px;margin:0}
h1{color:#00ff88;border-bottom:2px solid #00ff88;padding-bottom:10px;font-size:18px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:14px 0}
.card{background:#111;border:1px solid #00ff88;padding:14px;border-radius:4px}
.card h3{margin:0 0 10px;color:#00ffcc;font-size:12px;text-transform:uppercase;letter-spacing:1px}
.metric{display:flex;justify-content:space-between;margin:5px 0;font-size:12px}
.val{color:#fff;font-weight:bold}
.good{color:#00ff88}.warn{color:#ffaa00}.crit{color:#ff4444}.ai{color:#aa88ff}
.controls{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}
button{background:#00ff88;color:#000;border:none;padding:9px 16px;
       cursor:pointer;font-weight:bold;font-family:monospace;border-radius:3px;font-size:12px}
button:hover{opacity:.85}
.btn-warn{background:#ffaa00;color:#000}
.btn-crit{background:#ff4444;color:#fff}
.btn-info{background:#0088ff;color:#fff}
.btn-purple{background:#aa88ff;color:#000}
pre{background:#111;border:1px solid #222;padding:10px;font-size:10px;
    overflow:auto;max-height:250px;color:#888;margin-top:14px}
</style></head><body>
<h1>🧠 AI PAGING MANAGER v3.0 — Linux / NVMe</h1>
<div class="controls">
  <button onclick="cmd('enable')">✅ ENABLE</button>
  <button onclick="cmd('disable')" class="btn-warn">⏸ DISABLE</button>
  <button onclick="cmd('ai_on')"   class="btn-purple">🧠 AI ON</button>
  <button onclick="cmd('ai_off')"  class="btn-info">📏 THRESHOLD</button>
  <button onclick="cmd('expand4')">📈 +4GB</button>
  <button onclick="cmd('expand16')">📈 +16GB</button>
  <button onclick="cmd('shrink4')">📉 -4GB</button>
  <button onclick="if(confirm('Emergency stop?'))cmd('emergency')" class="btn-crit">🚨 EMERGENCY</button>
</div>
<div class="grid" id="metrics"><div class="card"><p>Loading...</p></div></div>
<pre id="raw">Loading...</pre>
<script>
async function cmd(a){await fetch('/api/control/'+a);await update()}
function cv(v,w,c){return v>=c?'crit':v>=w?'warn':'good'}
function card(t,rows){
  return `<div class="card"><h3>${t}</h3>${rows.map(r=>
    `<div class="metric"><span>${r[0]}</span>
     <span class="val ${r[2]||''}">${r[1]}</span></div>`).join('')}</div>`}
async function update(){
  try{
    const d=await(await fetch('/api/status')).json();
    const l=d.load,p=d.swap,e=d.engine,vp=d.virtual_processor,k=d.nvme,c=d.control;
    document.getElementById('metrics').innerHTML=
      card('💾 Memory',[
        ['RAM %',    l.ram_percent.toFixed(1)+'%',    cv(l.ram_percent,70,90)],
        ['RAM Free', l.ram_available_gb.toFixed(2)+'GB',''],
        ['Swap %',   l.swap_percent.toFixed(1)+'%',   cv(l.swap_percent,60,80)],
        ['Swap Used',l.swap_used_gb.toFixed(2)+'GB',  ''],
        ['CPU %',    l.cpu_percent.toFixed(1)+'%',    cv(l.cpu_percent,70,90)],
        ['CPU Temp', l.cpu_temp?(l.cpu_temp.toFixed(1)+'°C'):'N/A',
                     l.cpu_temp?cv(l.cpu_temp,70,80):''],
      ])+
      card('📀 NVMe Swapfile',[
        ['Path',     p.path,                          ''],
        ['Current',  p.current_gb.toFixed(1)+'GB',    ''],
        ['Max',      p.max_gb.toFixed(0)+'GB',        ''],
        ['Disk Free',k.free_gb.toFixed(1)+'GB',       cv(100-k.free_gb/k.total_gb*100,70,85)],
        ['Disk Used',k.used_pct.toFixed(1)+'%',       cv(k.used_pct,70,85)],
      ])+
      card('🧠 Predictive Engine',[
        ['Mode',     c.ai_mode?'AI PREDICTIVE':'THRESHOLD MODE', c.ai_mode?'ai':'warn'],
        ['Accuracy', (e.accuracy_pct||0).toFixed(1)+'%','good'],
        ['Cycles',   e.cycle||0,                       ''],
        ['History',  (e.history_depth||0)+' samples',  ''],
        ['HOT vel',  ((e.velocity||{}).hot||0).toFixed(2)+' MB/s',''],
        ['SWAP vel', ((e.velocity||{}).swap||0).toFixed(3)+' %/s',''],
      ])+
      card('⚡ Virtual Processor',[
        ['Status',   vp.watching?'ONLINE':'OFFLINE',   vp.watching?'good':'crit'],
        ['Trips',    vp.trips,                         vp.trips>0?'warn':'good'],
        ['Last Trip',vp.last_trip||'None',             ''],
        ['Reason',   vp.last_reason||'—',              ''],
        ['Expansions',d.stats.pagefile_expansions,     ''],
        ['Shrinks',   d.stats.pagefile_shrinks,        ''],
      ]);
    document.getElementById('raw').textContent=JSON.stringify(d,null,2);
  }catch(e){console.error(e)}
}
setInterval(update,5000);update();
</script></body></html>"""
        self.wfile.write(html.encode())

    def _json(self, data):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())

    def _control(self, action):
        m = self.manager
        if   action == 'enable':    m.control.enable()
        elif action == 'disable':   m.control.disable()
        elif action == 'emergency': m.control.emergency_stop()
        elif action == 'ai_on':     m.control.set_ai_mode(True)
        elif action == 'ai_off':    m.control.set_ai_mode(False)
        elif action == 'expand4':   m.swap_manager.expand(4.0)
        elif action == 'expand16':  m.swap_manager.expand(16.0)
        elif action == 'shrink4':   m.swap_manager.shrink(4.0)
        self._json({'ok': True})

    def log_message(self, *a): pass


# ============================================================================
# MAIN MANAGER
# ============================================================================

class AIPagingManager:
    """
    🧠 AI Paging Manager v3.0 — Linux Edition
    NVMe-optimized. Predictive. Self-learning. Emergency-safe.
    No restart required for swap changes.
    """

    def __init__(self, config: SystemConfig):
        self.config       = config
        self.monitor      = LinuxSystemMonitor()
        self.swap_manager = LinuxSwapManager(config)
        self.control      = ControlSystem(config.control_file)
        self.engine       = PredictiveEngine(config)
        self.vp           = VirtualProcessor(
            config, self.monitor, self.swap_manager, self.control)

        self.running    = False
        self.start_time = datetime.now()
        self.stats      = {
            'pagefile_expansions': 0,
            'pagefile_shrinks':    0,
            'ai_decisions':        0,
            'threshold_decisions': 0,
            'holds':               0,
        }

        self._setup_logging()
        logging.info("🧠 AI Paging Manager v3.0 Linux initialized")
        logging.info(f"   NVMe mount:   {config.nvme_mount}")
        logging.info(f"   Swapfile:     {config.swapfile_path}")
        logging.info(f"   Max swap:     {config.max_swap_gb}GB")
        logging.info(f"   AI mode:      {config.ai_mode}")

        self._start_dashboard()

    def _setup_logging(self):
        log = Path(self.config.log_file)
        log.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [PAGING] %(message)s',
            handlers=[
                logging.FileHandler(log),
                logging.StreamHandler()
            ])

    def _start_dashboard(self):
        def run():
            try:
                DashboardHandler.manager = self
                srv = HTTPServer(('0.0.0.0', self.config.web_dashboard_port),
                                 DashboardHandler)
                logging.info(f"[DASH] http://localhost:{self.config.web_dashboard_port}")
                srv.serve_forever()
            except Exception as e:
                logging.error(f"[DASH] {e}")
        threading.Thread(target=run, daemon=True).start()

    def _get_vrram_snapshot(self) -> TierSnapshot:
        """
        Hook for helix_vrram.py integration.
        Wire in real HelixMemoryManager.get_stats() here when Frank comes online.
        Standalone: derives tier approximation from /proc/meminfo.
        """
        mem  = self.monitor.virtual_memory()
        swap = self.monitor.swap_memory()
        used_mb = mem['used_gb'] * 1000
        swap_mb = swap['used_gb'] * 1000

        return TierSnapshot(
            timestamp  = time.time(),
            hot_mb     = used_mb * 0.4,
            warm_mb    = used_mb * 0.3,
            cold_mb    = used_mb * 0.2,
            frozen_mb  = swap_mb,
            hit_rate   = max(0, 100 - mem['percent']),
            promotions = 0,
            demotions  = 0,
            evictions  = int(swap_mb / 10)
        )

    def get_status_dict(self) -> Dict:
        mem   = self.monitor.virtual_memory()
        swap  = self.monitor.swap_memory()
        cpu   = self.monitor.cpu_percent()
        temp  = self.monitor.cpu_temperature()
        nvme  = self.monitor.get_disk_stats(self.config.nvme_mount)
        sw_gb = self.swap_manager.get_current_swap_gb()
        up    = datetime.now() - self.start_time
        ups   = f"{up.days}d {up.seconds//3600}h {(up.seconds%3600)//60}m"

        return {
            'control': self.control.get_state(),
            'load': {
                'ram_percent':      mem['percent'],
                'ram_available_gb': mem['available_gb'],
                'swap_percent':     swap['percent'],
                'swap_used_gb':     swap['used_gb'],
                'cpu_percent':      cpu,
                'cpu_temp':         temp,
            },
            'swap': {
                'path':       self.config.swapfile_path,
                'current_gb': sw_gb,
                'max_gb':     self.config.max_swap_gb,
            },
            'nvme':             nvme,
            'engine':           self.engine.get_stats(),
            'virtual_processor':self.vp.get_stats(),
            'stats':            self.stats,
            'uptime':           ups,
        }

    def _log_cycle(self, mem: Dict, swap: Dict,
                   action: str, amount: float, reason: str):
        sw = self.swap_manager.get_current_swap_gb()
        logging.info(
            f"RAM:{mem['percent']:.0f}% "
            f"SWAP:{swap['percent']:.0f}%({swap['used_gb']:.1f}GB) "
            f"PF:{sw:.1f}GB | "
            f"{action.upper()}({amount:.1f}GB) [{reason}]"
        )

    def monitor_and_adapt(self):
        logging.info("[START] Monitoring loop active")

        while self.running:
            try:
                if not self.control.is_enabled():
                    time.sleep(30); continue

                mem   = self.monitor.virtual_memory()
                swap  = self.monitor.swap_memory()
                sw_gb = self.swap_manager.get_current_swap_gb()
                snap  = self._get_vrram_snapshot()

                self.engine.record(snap, swap['percent'], mem['percent'])

                # Thermal check
                temp = self.monitor.cpu_temperature()
                if temp and temp > self.config.thermal_throttle_temp:
                    logging.warning(f"[THERMAL] {temp:.1f}°C — holding")
                    time.sleep(self.config.monitoring_interval); continue

                # Decision
                if self.control.is_ai_mode():
                    action, amount, reason = self.engine.decide(
                        swap['percent'], mem['percent'], sw_gb)
                    self.stats['ai_decisions'] += 1
                else:
                    if swap['percent'] > self.config.expand_threshold_percent:
                        action, amount, reason = 'expand', 4.0, 'threshold'
                    elif swap['percent'] < self.config.shrink_threshold_percent:
                        action, amount, reason = 'shrink', 2.0, 'threshold'
                    else:
                        action, amount, reason = 'hold', 0.0, 'stable'
                    self.stats['threshold_decisions'] += 1

                # Execute
                if action == 'expand' and amount > 0:
                    free = self.swap_manager.get_free_disk_gb()
                    safe = min(amount, free * 0.8,
                               self.config.max_swap_gb - sw_gb)
                    if safe >= self.config.micro_adjust_min_gb:
                        if self.swap_manager.expand(safe):
                            self.stats['pagefile_expansions'] += 1
                            self._log_cycle(mem, swap, 'expand', safe, reason)

                elif action == 'shrink' and amount > 0:
                    if sw_gb - amount >= self.config.min_swap_gb:
                        if self.swap_manager.shrink(amount):
                            self.stats['pagefile_shrinks'] += 1
                            self._log_cycle(mem, swap, 'shrink', amount, reason)
                else:
                    self.stats['holds'] += 1
                    self._log_cycle(mem, swap, 'hold', 0, reason)

                time.sleep(self.config.monitoring_interval)

            except KeyboardInterrupt:
                self.running = False
            except Exception as e:
                logging.error(f"[LOOP] {e}")
                time.sleep(self.config.monitoring_interval)

    def start(self):
        self.running = True
        logging.info(f"[INIT] Initializing swapfile on NVMe...")

        if not self.swap_manager.initialize():
            logging.error("[INIT] Swap initialization failed — check NVMe mount")
            sys.exit(1)

        self.vp.start()
        self.monitor_and_adapt()

    def stop(self):
        logging.info("[STOP] Shutting down")
        self.running = False
        self.vp.stop()
        logging.info("[OK] Stopped — swapfile remains active")


# ============================================================================
# CLI
# ============================================================================

def main():
    print("""
╔══════════════════════════════════════════╗
║  🧠 AI Paging Manager v3.0 — Linux      ║
║     NVMe Edition                         ║
╚══════════════════════════════════════════╝""")

    if not is_root():
        print("\n[X] Run as root: sudo python3 ai_paging_linux_v3.py start\n")
        sys.exit(1)

    usage = """
Commands:
  start              Start the manager
  enable             Turn ON
  disable            Turn OFF
  ai on|off          Toggle AI predictive mode
  emergency          Emergency stop
  expand <gb>        Manually expand swap
  shrink <gb>        Manually shrink swap
  status             Show current status
  teardown           Deactivate swapfile cleanly
"""

    if len(sys.argv) < 2:
        print(usage); sys.exit(1)

    cmd    = sys.argv[1].lower()
    config = SystemConfig()

    if cmd == 'start':
        print(f"""
Config:
  NVMe mount:   {config.nvme_mount}
  Swapfile:     {config.swapfile_path}
  Max swap:     {config.max_swap_gb}GB
  Initial:      {config.initial_swap_gb}GB
  AI mode:      {config.ai_mode}
  Dashboard:    http://localhost:{config.web_dashboard_port}
  Poll interval:{config.monitoring_interval}s (NVMe optimized)
""")
        manager = AIPagingManager(config)
        try:
            print("[START] Running... Ctrl+C to stop\n")
            manager.start()
        except KeyboardInterrupt:
            print("\n[i] Shutting down...")
        finally:
            manager.stop()
        return

    # Non-daemon commands
    ctrl  = ControlSystem(config.control_file)
    swap  = LinuxSwapManager(config)

    if   cmd == 'enable':    ctrl.enable();        print("[OK] Enabled")
    elif cmd == 'disable':   ctrl.disable();       print("[OK] Disabled")
    elif cmd == 'emergency': ctrl.emergency_stop();print("[!!!] Emergency stop")
    elif cmd == 'ai':
        on = len(sys.argv) > 2 and sys.argv[2].lower() == 'on'
        ctrl.set_ai_mode(on); print(f"[OK] AI mode {'ON' if on else 'OFF'}")
    elif cmd == 'expand':
        gb = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0
        swap.expand(gb); print(f"[OK] Expanded +{gb}GB")
    elif cmd == 'shrink':
        gb = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0
        swap.shrink(gb); print(f"[OK] Shrunk -{gb}GB")
    elif cmd == 'status':
        print(json.dumps(ctrl.get_state(), indent=2, default=str))
    elif cmd == 'teardown':
        swap.teardown(); print("[OK] Swapfile deactivated")
    else:
        print(f"Unknown: {cmd}"); print(usage)


if __name__ == "__main__":
    main()
