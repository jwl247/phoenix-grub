# Phoenix-DevOps-oS — Quick Start
> You built this. Here's how to use it.

---

## The Three Layers

```
LAYER 1 — BOOT        Phoenix USB key controls GRUB
LAYER 2 — AUTH        Same USB key controls login / sudo / SSH
LAYER 3 — SYSTEM      UnitedSys manages everything running on top
```

USB key in → you're in. USB key out → wall. No exceptions.

---

## Daily Commands

### Navigation
```bash
phoenix          # go to ~/phoenix
sec4             # go to SECTOR4
coms1            # go to coms1 ring
coms2            # go to coms2 ring
coms3            # go to coms3 ring
coms4            # go to coms4 ring
pscripts         # go to phoenix/scripts
cpool            # go to /mnt/clonepool
```

### UnitedSys (usys)
```bash
ul               # list all registered packages
ur <file> <name> # register a new file
uc <name>        # run a registered package
ui <name>        # see version history
uw <name>        # find where it lives on disk
us <name> <file> # hotswap to a new version
urb <name>       # roll back one version
urb <name> 2     # roll back to specific version number
uss <query>      # search the registry
```

### SECTOR4 — the kernel pipeline
```bash
pcs              # run the PCS engine test
freewheel        # run the Freewheeling stage test
cpt              # run Cpt_conductor test
```

### Clonepool
```bash
clonepool        # list color zones
zones            # list btrfs subvolumes
```

### Auth log (USB key)
```bash
keylog           # last 20 auth events
keyok            # successful key auths only
keyfail          # denied attempts only
```

### Git (phoenix-grub repo)
```bash
gstat            # git status
glog             # last 10 commits
gadd <file>      # stage a file
gcommit          # commit
gpush            # push to GitHub
```

### System
```bash
rings            # check coms ring service status
syslog           # tail journal
```

---

## UnitedSys — How It Works

Every script in Phoenix is registered in usys. Think of it like a package manager that lives entirely in `~/.usys/` — no sudo, no apt, no internet required.

```
~/.usys/
  bin/        ← symlinks, these go on your PATH
  versions/   ← every version of every file ever registered
  usys.db     ← SQLite registry
  log/        ← audit trail
```

When you `usys swap` or `usys rollback`, the symlink in `bin/` is atomically updated. Nothing breaks mid-flight.

---

## Currently Registered (17 packages)

| Name | Type | What it does |
|---|---|---|
| usys | shell | the registry itself |
| pcs | python | Proximity Control String engine |
| freewheeling-stage | python | 3-call lifecycle stage manager |
| conductor | python | Cpt_conductor kernel bridge |
| freewheeling | python | coms4 memory bank |
| franken | python | FrankenHelix load balancer |
| helix-api | python | Propcoms / ring validator |
| paging | python | paging system |
| guardian | python | integrated file guardian |
| conductor-sync | python | conductor sync module |
| cpt-conductor | python | alternate conductor entry |
| syncthing | python | syncthing module |
| rebound | shell | rebound handler |
| build_phoenix | shell | USB key builder |
| gen_key | shell | key generator |
| install_phoenix_grub | shell | GRUB installer |
| recover_scripts | shell | script recovery tool |

---

## The Phoenix Stack at a Glance

```
USB KEY
  └── GRUB (boot control)
  └── PAM  (login / sudo / SSH)

CLONEPOOL  /mnt/clonepool
  ├── @red      (physics)
  ├── @green    (network)
  ├── @blue     (ai)
  ├── @cyan     (assets)
  ├── @magenta  (system)
  └── @yellow   (user)

SECTOR4  — the kernel pipeline
  PCS → Freewheeling → Cpt_conductor → Propcoms → coms rings

  PCS (Proximity Control String)
    format:  {hash}:{zipcode}:{p1}:{p2}:{p3}:{definitive}
    example: a1b2c3d4e5f6a7b8:red:72:85:94:1

  3-Call Lifecycle
    Call 1 — stage set, PCS born
    Call 2 — flock accumulates, probability climbs
    Call 3 — definitive hit → snap-clone fires → clonepool

  Kernel Slots
    Slot 0  c_pure       → VECTOR     (physics, system — max speed)
    Slot 1  c_sideload   → NOSQL      (network, assets — balanced)
    Slot 2  python_user  → RELATIONAL (user — flexible)
    Slot 3  python_full  → TIMESERIES (ai — full flex)

  Rings
    coms1  red + cyan     → system_1
    coms2  green + magenta → system_2
    coms3  blue + yellow  → system_3
    coms4  peers system_1

UNITEDSY (usys)
  ~/.usys/bin on PATH — call anything by name
```

---

## GitHub

**Repo:** `jwl247/phoenix-grub`

All source is there. Push with `gpush` from anywhere.

---

*Built from scratch, one session, post-attack. Phoenix rises.*
