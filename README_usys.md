# UnitedSys (usys)

Universal file registration, versioning, and hotswap registry for scripts and tools.

Register any script or file by name, call it from anywhere, swap it live without restarts, and roll back to any previous version — all tracked in a local SQLite database with no sudo required.

---

## Features

- **Register anything** — shell scripts, Python, Node, Ruby, Go, binaries
- **Call by name** — no paths, no aliases, just `usys call <name>`
- **Hotswap live** — swap to a new version instantly, zero downtime
- **Rollback** — go back to any previous version with one command
- **Full version history** — every version stored and logged
- **Clone with history** — copy a package and its full history to another location
- **No sudo required** — lives entirely in `~/.usys/`
- **Zero dependencies** — bash + sqlite3 only

---

## Requirements

- `bash` 4+
- `sqlite3`

```bash
# Debian/Ubuntu
sudo apt install sqlite3

# Fedora/RHEL
sudo dnf install sqlite
```

---

## Install

```bash
git clone https://github.com/jwl247/unitedsys
cd unitedsys
bash usys.sh init
source ~/.bashrc   # or open a new terminal
```

`init` sets up `~/.usys/`, initializes the database, and adds `~/.usys/bin` to your PATH.

---

## Quick Start

```bash
# Register a script
usys register ./deploy.sh deploy

# Call it from anywhere
usys call deploy

# Or directly once PATH is set
deploy

# Push a new version live
usys swap deploy ./deploy_v2.sh

# Something broke — roll back
usys rollback deploy

# Roll back to a specific version
usys rollback deploy v1
```

---

## Commands

### `usys init`
First-time setup. Creates `~/.usys/`, initializes the SQLite database, and configures PATH.

```bash
usys init
```

---

### `usys register <file> <name>`
Register a file under a name. A versioned copy is stored and a callable wrapper is created in `~/.usys/bin/`.

```bash
usys register ./intake.sh intake
usys register ./server.py api
usys register ./build.sh build "production build script"
```

---

### `usys call <name> [args...]`
Call a registered file by name, passing any arguments through.

```bash
usys call intake
usys call deploy --env production
```

Once `~/.usys/bin` is in your PATH you can also call directly:

```bash
intake
deploy --env production
```

---

### `usys swap <name> <newfile> [note]`
Hotswap a registered file to a new version. The new version goes live immediately — no restart needed. The old version is kept in history.

```bash
usys swap deploy ./deploy_v2.sh
usys swap api ./server_fixed.py "hotfix for null pointer"
```

---

### `usys rollback <name> [version]`
Roll back to the previous version, or a specific version. Live immediately.

```bash
usys rollback deploy          # previous version
usys rollback deploy v1       # specific version
```

---

### `usys list`
List all registered packages with current version, type, and last updated.

```bash
usys list
```

```
  UnitedSys Registry  —  4 package(s)
  ─────────────────────────────────────────────────
  NAME                 VERSION  TYPE        UPDATED
  ─────────────────────────────────────────────────
  build_phoenix        v1       shell       2026-03-08
  deploy               v3       shell       2026-03-08
  api                  v2       python      2026-03-08
  intake               v1       shell       2026-03-08
  ─────────────────────────────────────────────────
```

---

### `usys info <name>`
Show full version history, swap log, file type, and source path for a package.

```bash
usys info deploy
```

---

### `usys where <name>`
Show the stored path and original source path for a package.

```bash
usys where deploy
```

---

### `usys remove <name>`
Unregister a package. The callable wrapper is removed but stored versions are kept on disk.

```bash
usys remove deploy
```

---

### `usys sync <name> <dest>`
Copy the current version of a package to a destination path.

```bash
usys sync deploy /usr/local/bin/deploy
usys sync backup /media/jwl247/drive/backup.sh
```

---

### `usys clone <name> <dest>`
Clone a package with its full version history to a destination directory.

```bash
usys clone intake /media/jwl247/backup_drive/
usys clone deploy ~/exports/
```

---

### `usys search <query>`
Search the registry by name, type, or description.

```bash
usys search deploy
usys search python
```

---

### `usys version`
Show the usys version.

```bash
usys version
```

---

## How It Works

```
~/.usys/
├── usys.db              # SQLite registry (packages, versions, swaplog)
├── usys.sh              # usys itself
├── bin/                 # callable wrappers — add this to PATH
│   ├── deploy           # wrapper → queries DB → exec current version
│   └── intake
└── versions/            # versioned file store
    ├── deploy/
    │   ├── v1_deploy.sh
    │   ├── v2_deploy.sh
    │   └── v3_deploy.sh
    └── intake/
        └── v1_intake.sh
```

Each callable in `~/.usys/bin/` is a small bash wrapper that queries the database for the current version path and execs it. Hotswapping updates the database record — the wrapper automatically picks up the new version on the next call.

---

## Database Schema

Three tables:

| Table | Purpose |
|---|---|
| `packages` | One row per registered name — current version, source, type |
| `versions` | Every version ever registered — path, hash, size, timestamp |
| `swaplog` | Full audit log of every register, swap, and rollback |

Query directly at any time:

```bash
sqlite3 ~/.usys/usys.db "SELECT name, current_ver, updated FROM packages;"
sqlite3 ~/.usys/usys.db "SELECT * FROM swaplog ORDER BY id DESC LIMIT 10;"
```

---

## License

GPL v3 — use it, share it, build on it.
