# Phoenix-DevOps-oS

> *One key. Any machine. Full control.*

Phoenix is a portable, self-contained operations system built around a single USB key. Plug it in — GRUB boots from it, Linux authenticates through it, and your entire toolkit travels with it. Pull it out — the machine locks.

No passwords. No agents. No dependencies on the host. The key is the system.

---

## The Stack

```
┌─────────────────────────────────────────────────────┐
│                   PHOENIX USB KEY                   │
│                  (PHOENIX-KEY label)                │
│                                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│  │  GRUB Boot  │  │  PAM Auth   │  │  usys Tools │ │
│  │  Controller │  │   Token     │  │   Registry  │ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘ │
└─────────┼────────────────┼────────────────┼─────────┘
          │                │                │
          ▼                ▼                ▼
    Boot any machine   Login/sudo/ssh   Call any tool
    detect all OSes    no password      from anywhere
    load to RAM        key = identity   versioned, live
```

Three components. One key. The USB is the root of trust for the entire system.

---

## Components

### 1. Phoenix GRUB Boot Controller

A custom GRUB bootloader that lives on the USB, loads itself into RAM on boot, and presents a unified menu across any machine it encounters.

**What it does:**
- Auto-detects every OS on every drive — Linux, Windows, LVM, btrfs — no hardcoded paths
- Loads fully to RAM on boot so the USB can be removed after the menu appears
- Validates the `.phoenix_key` file on boot — key present unlocks the full ops menu
- Without the key: boot-only access to detected systems
- With the key: full recovery and ops menu

**Ops menu (key required):**
- Recovery shell — drops to bash on the first bootable partition found
- Script recovery — boots and auto-runs `recover_scripts.sh` across all drives
- Clone mode — read-only boot for safe `dd`/`rsync` operations
- Lifeboat — boots a dedicated rescue partition by label
- GRUB shell — raw GRUB console for manual intervention
- btrfs vault scanner — lists all btrfs partitions across drives
- Install Phoenix GRUB permanently to disk

**Build the USB:**
```bash
sudo ./scripts/build_now.sh          # non-interactive, targets /dev/sdg
# or
sudo ./scripts/build_phoenix_usb.sh /dev/sdX   # interactive, any device
```

**Generate the key:**
```bash
sudo ./scripts/gen_key.sh /dev/sdX
```

The key is a SHA-256 hash derived from your machine ID, timestamp, and random bytes. The hash is written as a hidden `.phoenix_key` file on the USB and stored locally at `keys/key.hash` for GRUB and PAM to verify against.

**Install GRUB permanently to disk:**
```bash
sudo ./scripts/install_phoenix_grub.sh /dev/sdX
```

---

### 2. Phoenix PAM Authentication

The same USB key that controls GRUB also authenticates Linux. When you plug in the key, `sudo`, `login`, and `sshd` all authenticate through it — no password prompt, no SSH keys, no other bypass.

**How it works:**

`pam_phoenix_key.sh` is called by `pam_exec.so` at the top of the auth stack for each service. It scans mounted filesystems, then falls back to mounting the USB by label, then scans all removable block devices. If the `.phoenix_key` hash matches `keys/key.hash`, auth succeeds immediately. If not, hard deny — no fallback.

```
PAM auth stack (sudo / login / sshd):

  pam_exec.so → pam_phoenix_key.sh
       │
       ├── key found + hash matches → [success=done] → authenticated
       │                                                no password asked
       └── key absent or wrong hash → [default=die]  → hard denied
                                                        no fallback
```

**Services protected:** `sudo`, `login`, `sshd`

**SSH hardening applied:**
- `KbdInteractiveAuthentication yes` — PAM fires for SSH auth
- `PasswordAuthentication no` — no password bypass
- `PubkeyAuthentication no` — no SSH key bypass
- `PermitRootLogin no`
- `X11Forwarding no`, `AllowTcpForwarding no`
- `MaxAuthTries 3`, `LoginGraceTime 30`

**Audit log:** every auth attempt (success and failure) is logged to `/var/log/phoenix_auth.log`:
```
[2026-03-08 19:09:39] [OK]   service=sshd user=jwl247 tty=ssh key matched via label mount
[2026-03-08 19:11:02] [FAIL] service=sshd user=jwl247 tty=ssh key not found on any device
```

**Install PAM auth:**
```bash
# Already wired in if you cloned this repo and ran the build
# Manual: add to top of auth section in /etc/pam.d/sudo|login|sshd:
auth [success=done default=die] pam_exec.so quiet /path/to/scripts/pam_phoenix_key.sh
```

---

### 3. UnitedSys (usys)

A portable script and tool registry. Register any script by name, call it from anywhere, swap it live without restarts, roll back to any version. The full registry travels with you on the USB.

```bash
usys register ./deploy.sh deploy       # register
usys call deploy --env prod            # call by name
usys swap deploy ./deploy_v2.sh        # hotswap live
usys rollback deploy                   # roll back
usys clone deploy /media/PHOENIX-KEY/  # push to USB
```

See [README_usys.md](README_usys.md) for full documentation.

---

## The Flow

```
1. Plug in USB
        │
        ▼
2. Boot machine  →  GRUB loads from USB to RAM
                     USB can stay in or be pulled after menu
        │
        ▼
3. Select OS     →  Boots detected Linux/Windows/LVM
        │
        ▼
4. Login prompt  →  PAM checks USB for .phoenix_key
                     Key present  →  authenticated, no password
                     Key absent   →  hard denied
        │
        ▼
5. sudo / ssh    →  Same check, same key, same result
        │
        ▼
6. Run tools     →  usys registry carries your toolkit
                     call anything by name, swap live
```

---

## Directory Structure

```
phoenix/
├── grub/
│   └── grub.cfg                  # Master GRUB boot controller config
├── keys/
│   ├── key.hash                  # SHA-256 hash of the active key
│   └── key.id                    # MD5 key identifier
├── scripts/
│   ├── build_phoenix_usb.sh      # Build bootable USB (interactive)
│   ├── build_now.sh              # Build USB non-interactive (/dev/sdg)
│   ├── gen_key.sh                # Generate and write key to USB
│   ├── install_phoenix_grub.sh   # Install GRUB permanently to disk
│   ├── pam_phoenix_key.sh        # PAM auth module
│   └── recover_scripts.sh        # Multi-drive script recovery
├── usys.sh                       # UnitedSys package registry
├── README.md                     # This file
└── README_usys.md                # UnitedSys documentation
```

---

## Backup Key

Run `gen_key.sh` on a second USB to create a backup key. Both keys will verify against the same stored hash — or generate a new hash pair and update `grub.cfg` and `keys/key.hash` for a fully independent backup key.

```bash
sudo ./scripts/gen_key.sh /dev/sdY   # second USB
```

---

## Recovery Without the Key

If the USB is lost, access requires physical presence:

1. Boot from a live USB (Kali, Ubuntu, etc.)
2. Mount the root partition
3. Replace `keys/key.hash` with a new key's hash
4. Update `grub/grub.cfg` with the new hash
5. Run `gen_key.sh` on a new USB

There is no remote recovery path by design.

---

## License

GPL v3 — use it, share it, build on it.

---

*Phoenix-DevOps-oS — jwl247*
