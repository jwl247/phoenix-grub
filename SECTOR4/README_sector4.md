# SECTOR4 — The Kernel Pipeline
> PCS → Freewheeling → Cpt_conductor → Propcoms → coms rings

---

## What SECTOR4 Does

SECTOR4 intercepts data at the earliest possible input, routes it through a probability-based lifecycle, and commits definitive outcomes to the clonepool via btrfs snapshot. Everything is ingress/egress — no loops, ever.

```
DATA IN
  │
  ▼
PCS born (BLAKE2s hash, zipcode assigned, probability chain starts)
  │
  ▼
Freewheeling Stage (3-call lifecycle — birds of a feather flock together)
  │
  ▼
snap-clone fires on definitive outcome (btrfs → clonepool zone)
  │
  ▼
Cpt_conductor (kernel slot selected, data wrapped in QuadPacket)
  │
  ▼
Propcoms validates (zipcode check — nothing reaches a ring without clearance)
  │
  ▼
coms ring handles post-stage
```

---

## Files

| File | What it is |
|---|---|
| `pcs.py` | PCS engine — the identity and lifecycle of every signal |
| `freewheeling_stage.py` | Stage manager — owns the 3-call lifecycle |
| `conductor.py` | Cpt_conductor — kernel bridge, quadralingual custody |
| `helix_api.py` | Propcoms + FrankenHelix — ring validator and load balancer |
| `coms1/` | Ring 1 — red + cyan zones |
| `coms2/` | Ring 2 — green + magenta zones |
| `coms3/` | Ring 3 — blue + yellow zones |
| `coms4/` | Ring 4 — peers through system_1 |

---

## PCS — Proximity Control String

Every signal in Phoenix has a PCS. Born at first input. Carries its own destination. Never loses its identity.

### Format
```
{hash16}:{zipcode}:{p1}:{p2}:{p3}:{definitive}
a1b2c3d4e5f6a7b8:red:72:85:94:1
```

| Field | What it means |
|---|---|
| `hash16` | BLAKE2s truncated to 8 bytes = 16 hex chars. 75% smaller than SHA-256. |
| `zipcode` | DB-assigned address — where this data belongs in the clonepool |
| `p1` | Probability after Call 1 (0–100) |
| `p2` | Probability after Call 2 — hash absorbed new data |
| `p3` | Probability after Call 3 — definitive check |
| `definitive` | 1 = p3 ≥ 90, snap-clone fires. 0 = still accumulating |

### The 3-Call Lifecycle

```
Call 1 — stage pre-positioned, PCS born, slot reserved
          pcs.call1()
          p1 derived from hash

Call 2 — flock accumulates, new data absorbed
          pcs.call2(new_data)
          hash re-hashed with new data, p2 calculated

Call 3 — final accumulation, definitive check
          pcs.call3(final_data)
          p3 calculated — if p3 >= 90: definitive = True → snap-clone fires
```

### Zipcode → Zone map (family-based)

| Family | Zipcode | Clonepool zone |
|---|---|---|
| physics | red | `/mnt/clonepool/@red` |
| network | green | `/mnt/clonepool/@green` |
| ai | blue | `/mnt/clonepool/@blue` |
| assets | cyan | `/mnt/clonepool/@cyan` |
| system | magenta | `/mnt/clonepool/@magenta` |
| user | yellow | `/mnt/clonepool/@yellow` |

Birds of a feather flock together — same family always lands in same zone.

---

## Freewheeling — The Stage

Freewheeling IS the stage. Storage is tied directly to it. It manages all active PCS slots.

```python
stage = FreewheelStage()

# Call 1 — pre-position
pcs = stage.call1(data, family="physics")
orig_hash = pcs.hash    # IMPORTANT: save original hash — it mutates on call2/call3

# Call 2 — accumulate
stage.call2(orig_hash, b"chunk:data")

# Call 3 — definitive check
pcs, committed = stage.call3(orig_hash, b"final:data")
# if committed == True: btrfs snapshot fired, slot released
```

### What happens on definitive commit

1. `snap_clone()` fires — btrfs snapshot from stage dir to clonepool zone
2. `_post_stage()` fires — signals `phoenix-cpt@{hash}.service` via systemctl
3. Captain receives signal, Propcoms validates, ring handles post-stage
4. Stage dir cleaned up — data now lives in clonepool

### Flock status
```python
stage.flock_status()    # snapshot of all active flocks
stage.active_count()    # how many slots in flight
```

---

## Cpt_conductor — The Kernel Bridge

Captain talks to the kernel only. Everything is ingress/egress. No loops.

```
ingress → kernel slot selection → QuadPacket → Propcoms gate → egress
```

### Kernel Slots

| Slot | Type | Storage language | Best for |
|---|---|---|---|
| 0 | c_pure | VECTOR | physics, system — max speed, peak traffic |
| 1 | c_sideload | NOSQL | network, assets — balanced, extended calls |
| 2 | python_user | RELATIONAL | user — flexible, moderate load |
| 3 | python_full | TIMESERIES | ai — full flexibility, dev |

Family automatically routes to preferred slot. If slot overloaded (>100 in-flight), routes to least loaded.

### QuadPacket — quadralingual custody

Every packet is quadralingual. Data stays in all 4 forms simultaneously while in custody. Language is never stripped.

```python
packet.as_vector()      # [float, float, ...]        — SLOT 0
packet.as_nosql()       # {"id":..., "pcs":..., ...} — SLOT 1
packet.as_relational()  # {"id":..., "ts":..., ...}  — SLOT 2
packet.as_timeseries()  # [{"ts":..., "metric":...}] — SLOT 3
packet.native()         # returns data in packet's own language
```

### Usage
```python
from conductor import CptConductor
from freewheeling_stage import FreewheelStage

cpt   = CptConductor()
stage = FreewheelStage()

pcs       = stage.call1(b"physics:collision:obj_1", "physics")
orig_hash = pcs.hash
stage.call2(orig_hash, b"chunk:alpha")
pcs, committed = stage.call3(orig_hash, b"outcome:final")

packet = cpt.ingress(pcs, {"ball": "physics:collision:obj_1"})
# packet.slot     → 0 (c_pure)
# packet.language → StorageLanguage.VECTOR
# packet.native() → [float, float, ...]

cpt.status()
# {in_flight: N, egress_count: N, kernel_load: {0:0,1:0,2:0,3:0}, ring_alive: True, seq: N}
```

---

## Propcoms — The Gate

One entity. Symlinked across all rings. Nothing reaches a ring without Propcoms clearance. Same validator everywhere.

```
Ring name → Propcoms system name
  coms1 → system_1
  coms2 → system_2
  coms3 → system_3
  coms4 → system_1  (peers through system_1)
```

Valid targets: `system_1`, `system_2`, `system_3`

If a target is invalid or flagged for escalation — packet is held. Captain tries fallback rings in order.

---

## Run the Tests

```bash
# PCS engine
cd ~/phoenix/SECTOR4
python3 pcs.py

# Freewheeling stage
python3 freewheeling_stage.py

# Full pipeline (PCS → Freewheeling → Cpt_conductor → Propcoms)
python3 conductor.py
```

Expected output from conductor test:
```
[physics ]  slot=0 (c_pure      )  lang=vector      id=CPT_000001
[ai      ]  slot=3 (python_full )  lang=timeseries  id=CPT_000002
[network ]  slot=1 (c_sideload  )  lang=nosql       id=CPT_000003
[system  ]  slot=0 (c_pure      )  lang=vector      id=CPT_000004
Status: {'in_flight': 4, 'egress_count': 4, 'kernel_load': {0:0,...}, 'ring_alive': True, 'seq': 4}
```

---

## What's Next for SECTOR4

- `phoenix-cpt@.service` — systemd template so post-stage signaling wires up for real
- QR code generator — TOP (grey shades = state), BOTTOM (color = clonepool zipcode)
- Hex file naming + sidecar metadata
- Frontend — point-and-click into the D1 schema / entry points
