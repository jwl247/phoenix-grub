#!/usr/bin/env python3
# 💎 GemIIIDev - J4 Approved Artifact
# HELIX AUDIT v1.0
# Scans SECTOR4 files and flags anything that lost its helix/quad structure

import os
import ast
import json
from pathlib import Path

SECTOR4 = Path("/etc/systemd/system/SECTOR4")

# Signatures that indicate a healthy helix variant
HELIX_SIGNATURES = [
    "threading", "Thread", "simultaneous", "streams", "quadrant",
    "EN", "ZH", "ES", "HI", "NeuralStream", "pulse", "buffer",
    "helix", "Helix", "quad", "Quad", "polyglot", "Polyglot"
]

# Red flags — signs something got unscrambled/flattened
FLAT_FLAGS = [
    "sequential", "for loop",  # logic hints
]

RESULTS = {
    "healthy": [],
    "missing_quad": [],
    "no_threading": [],
    "unscrambled": [],
    "skipped": []
}

def check_python_file(filepath):
    issues = []
    try:
        src = filepath.read_text(errors="ignore")
    except Exception as e:
        RESULTS["skipped"].append((str(filepath), str(e)))
        return

    found_sigs = [s for s in HELIX_SIGNATURES if s in src]
    
    # Check for threading (parallel streams)
    has_threading = "threading" in src or "Thread" in src

    # Check for all 4 stream codes
    streams_found = [s for s in ["EN", "ZH", "ES", "HI"] if f'"{s}"' in src or f"'{s}'" in src]

    # Check for sequential-only patterns (simple for loops over streams with no threads)
    has_sequential_risk = (
        "for " in src and
        not has_threading and
        any(s in src for s in ["streams", "stream", "quad", "lang"])
    )

    if not found_sigs:
        RESULTS["unscrambled"].append({
            "file": str(filepath),
            "reason": "No helix signatures found — may be fully flattened"
        })
    elif not has_threading and filepath.suffix == ".py":
        RESULTS["no_threading"].append({
            "file": str(filepath),
            "reason": f"Missing threading — streams may be sequential. Found: {found_sigs}"
        })
    elif len(streams_found) > 0 and len(streams_found) < 4:
        RESULTS["missing_quad"].append({
            "file": str(filepath),
            "reason": f"Only {len(streams_found)}/4 streams present: {streams_found}"
        })
    else:
        RESULTS["healthy"].append(str(filepath))

def check_json_file(filepath):
    try:
        data = json.loads(filepath.read_text(errors="ignore"))
        content = json.dumps(data)
        streams_found = [s for s in ["EN", "ZH", "ES", "HI"] if s in content]
        if not streams_found:
            RESULTS["missing_quad"].append({
                "file": str(filepath),
                "reason": "JSON has no stream/quad keys"
            })
        else:
            RESULTS["healthy"].append(str(filepath))
    except Exception as e:
        RESULTS["skipped"].append((str(filepath), str(e)))

def scan():
    print("💎 HELIX AUDIT — Scanning SECTOR4...\n")
    
    for f in SECTOR4.rglob("*"):
        if f.is_file():
            if f.suffix == ".py":
                check_python_file(f)
            elif f.suffix == ".json":
                check_json_file(f)
            elif f.suffix == ".sh":
                # Just check for helix signatures in shell scripts
                try:
                    src = f.read_text(errors="ignore")
                    found = [s for s in HELIX_SIGNATURES if s in src]
                    if found:
                        RESULTS["healthy"].append(str(f))
                except:
                    RESULTS["skipped"].append((str(f), "read error"))

    # Report
    print(f"✅ HEALTHY ({len(RESULTS['healthy'])}):")
    for f in RESULTS["healthy"]:
        print(f"   {f}")

    print(f"\n⚠️  MISSING QUAD STREAMS ({len(RESULTS['missing_quad'])}):")
    for r in RESULTS["missing_quad"]:
        print(f"   {r['file']}")
        print(f"      → {r['reason']}")

    print(f"\n🔴 NO THREADING — POSSIBLE SEQUENTIAL ({len(RESULTS['no_threading'])}):")
    for r in RESULTS["no_threading"]:
        print(f"   {r['file']}")
        print(f"      → {r['reason']}")

    print(f"\n💀 UNSCRAMBLED — NO HELIX SIGNATURE ({len(RESULTS['unscrambled'])}):")
    for r in RESULTS["unscrambled"]:
        print(f"   {r['file']}")
        print(f"      → {r['reason']}")

    print(f"\n⏭️  SKIPPED ({len(RESULTS['skipped'])}):")
    for f, reason in RESULTS["skipped"]:
        print(f"   {f} ({reason})")

    print("\n💎 Audit complete.")

if __name__ == "__main__":
    scan()
