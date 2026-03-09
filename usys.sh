#!/usr/bin/env bash
# ============================================================
#  UnitedSys  —  usys
#  Universal file registration, versioning, and hotswap
#
#  GPL v3 — use it, share it, build on it
#  https://github.com/jwl247/unitedsys
#
#  Zero dependencies beyond bash + sqlite3
#  No sudo required — lives entirely in ~/.usys/
#
#  Commands:
#    usys init                        — first time setup
#    usys register <file> <name>      — register a file
#    usys call <name> [args...]       — call a registered file
#    usys swap <name> <newfile>       — hotswap to new version
#    usys rollback <name> [version]   — roll back to previous
#    usys list                        — list all registered
#    usys info <name>                 — show version history
#    usys remove <name>               — unregister
#    usys where <name>                — show file location
#    usys sync <name> <dest>          — sync to destination
#    usys clone <name> <dest>         — clone with full history
#    usys search <query>              — search registry
#    usys version                     — show usys version
# ============================================================

set -euo pipefail

# ── Version ───────────────────────────────────────────────────
USYS_VERSION="0.1.0"

# ── Paths ─────────────────────────────────────────────────────
USYS_HOME="${USYS_HOME:-$HOME/.usys}"
USYS_DB="$USYS_HOME/usys.db"
USYS_BIN="$USYS_HOME/bin"
USYS_VERSIONS="$USYS_HOME/versions"
USYS_LOG="$USYS_HOME/log"

# ── Colors ────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# ── Helpers ───────────────────────────────────────────────────
info()  { echo -e "${CYAN}[usys]${RESET} $*"; }
ok()    { echo -e "${GREEN}[usys]${RESET} $*"; }
warn()  { echo -e "${YELLOW}[usys]${RESET} $*"; }
err()   { echo -e "${RED}[usys]${RESET} $*" >&2; }
die()   { err "$*"; exit 1; }

# ── Root warning ──────────────────────────────────────────────
check_sudo() {
    if [[ $EUID -eq 0 ]]; then
        echo -e "${YELLOW}"
        echo "  ⚠  WARNING: You are running usys as root."
        echo "     Packages will register to root's index,"
        echo "     not your user index. Most operations"
        echo "     do not require sudo."
        echo -e "${RESET}"
        # Only prompt if running interactively
        if [[ -t 0 ]]; then
            read -rp "  Continue as root? [y/N] " confirm
            [[ "$confirm" =~ ^[Yy]$ ]] || exit 0
        fi
    fi
}

# ── Require sqlite3 ───────────────────────────────────────────
require_sqlite() {
    command -v sqlite3 &>/dev/null || \
        die "sqlite3 not found. Install it:\n  Ubuntu/Debian: sudo apt install sqlite3\n  Fedora: sudo dnf install sqlite\n  RHEL: sudo dnf install sqlite"
}

# ── DB query helpers ──────────────────────────────────────────
db() {
    sqlite3 "$USYS_DB" "$@"
}

db_exec() {
    sqlite3 "$USYS_DB" << SQL
$*
SQL
}

# ── Init DB schema ────────────────────────────────────────────
init_db() {
    db << 'SQL'
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS packages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    UNIQUE NOT NULL,
    current_ver TEXT    NOT NULL,
    source_path TEXT,
    bin_path    TEXT,
    filetype    TEXT,
    executable  INTEGER DEFAULT 1,
    registered  TEXT    DEFAULT (datetime('now')),
    updated     TEXT    DEFAULT (datetime('now')),
    tags        TEXT    DEFAULT '',
    description TEXT    DEFAULT ''
);

CREATE TABLE IF NOT EXISTS versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    package     TEXT    NOT NULL,
    version     TEXT    NOT NULL,
    store_path  TEXT    NOT NULL,
    hash        TEXT    NOT NULL,
    size        INTEGER,
    created     TEXT    DEFAULT (datetime('now')),
    note        TEXT    DEFAULT '',
    FOREIGN KEY (package) REFERENCES packages(name) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS swaplog (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    package     TEXT    NOT NULL,
    from_ver    TEXT,
    to_ver      TEXT,
    action      TEXT    NOT NULL,
    ts          TEXT    DEFAULT (datetime('now')),
    note        TEXT    DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_versions_package ON versions(package);
CREATE INDEX IF NOT EXISTS idx_swaplog_package  ON swaplog(package);
SQL
}

# ── Generate version string ───────────────────────────────────
next_version() {
    local name="$1"
    local count
    count=$(db "SELECT COUNT(*) FROM versions WHERE package='$name';")
    echo "v$((count + 1))"
}

# ── File hash ─────────────────────────────────────────────────
file_hash() {
    sha256sum "$1" | awk '{print $1}'
}

# ── Detect filetype ───────────────────────────────────────────
detect_type() {
    local file="$1"
    local ext="${file##*.}"
    local shebang
    shebang=$(head -c 50 "$file" 2>/dev/null | grep -oE '^#![^\n]+' || echo "")

    if [[ -n "$shebang" ]]; then
        echo "$shebang" | grep -qE 'python' && echo "python" && return
        echo "$shebang" | grep -qE 'bash|sh'   && echo "shell"  && return
        echo "$shebang" | grep -qE 'node'   && echo "node"   && return
        echo "$shebang" | grep -qE 'ruby'   && echo "ruby"   && return
        echo "$shebang" | grep -qE 'perl'   && echo "perl"   && return
    fi

    case "$ext" in
        py|pyw)         echo "python" ;;
        sh|bash|zsh)    echo "shell"  ;;
        js|mjs)         echo "node"   ;;
        rb)             echo "ruby"   ;;
        pl)             echo "perl"   ;;
        php)            echo "php"    ;;
        go)             echo "go"     ;;
        *)
            file "$file" 2>/dev/null | grep -qi "executable" && echo "binary" || echo "file"
            ;;
    esac
}

# ── Create callable wrapper in ~/.usys/bin ────────────────────
make_callable() {
    local name="$1"
    local store_path="$2"
    local filetype="$3"
    local wrapper="$USYS_BIN/$name"

    cat > "$wrapper" << WRAPPER
#!/usr/bin/env bash
# UnitedSys callable wrapper — $name
# Auto-generated by usys — do not edit manually
# Edit via: usys swap $name <newfile>

USYS_TARGET=\$(sqlite3 "\$HOME/.usys/usys.db" \
    "SELECT v.store_path FROM packages p \
     JOIN versions v ON v.package=p.name AND v.version=p.current_ver \
     WHERE p.name='$name' LIMIT 1;" 2>/dev/null)

[[ -z "\$USYS_TARGET" ]] && {
    echo "[usys] ERROR: '$name' not found in registry" >&2
    exit 1
}

[[ -x "\$USYS_TARGET" ]] || chmod +x "\$USYS_TARGET" 2>/dev/null || true

exec "\$USYS_TARGET" "\$@"
WRAPPER

    chmod +x "$wrapper"
}

# ============================================================
#  COMMANDS
# ============================================================

# ── usys init ────────────────────────────────────────────────
cmd_init() {
    echo -e "${BOLD}"
    echo "  ██╗   ██╗███████╗██╗   ██╗███████╗"
    echo "  ██║   ██║██╔════╝╚██╗ ██╔╝██╔════╝"
    echo "  ██║   ██║███████╗ ╚████╔╝ ███████╗"
    echo "  ██║   ██║╚════██║  ╚██╔╝  ╚════██║"
    echo "  ╚██████╔╝███████║   ██║   ███████║"
    echo "   ╚═════╝ ╚══════╝   ╚═╝   ╚══════╝"
    echo "  UnitedSys v${USYS_VERSION} — universal hotswap registry"
    echo -e "${RESET}"

    require_sqlite

    mkdir -p "$USYS_HOME" "$USYS_BIN" "$USYS_VERSIONS" "$USYS_LOG"
    init_db
    ok "Database initialized: $USYS_DB"

    # Add to PATH if not already there
    local shell_rc=""
    if [[ -f "$HOME/.bashrc" ]];  then shell_rc="$HOME/.bashrc"; fi
    if [[ -f "$HOME/.zshrc" ]];   then shell_rc="$HOME/.zshrc";  fi

    local path_line="export PATH=\"\$HOME/.usys/bin:\$PATH\""
    local usys_line="alias usys=\"$USYS_BIN/../usys.sh\""

    if [[ -n "$shell_rc" ]]; then
        if ! grep -q "\.usys/bin" "$shell_rc" 2>/dev/null; then
            echo "" >> "$shell_rc"
            echo "# UnitedSys" >> "$shell_rc"
            echo "$path_line"  >> "$shell_rc"
            ok "Added ~/.usys/bin to PATH in $shell_rc"
        else
            info "PATH already configured in $shell_rc"
        fi
    fi

    # Copy self to usys home
    cp "$0" "$USYS_HOME/usys.sh" 2>/dev/null || true
    chmod +x "$USYS_HOME/usys.sh"

    # Create usys callable for usys itself
    ln -sf "$USYS_HOME/usys.sh" "$USYS_BIN/usys" 2>/dev/null || \
        cp "$USYS_HOME/usys.sh" "$USYS_BIN/usys"
    chmod +x "$USYS_BIN/usys"

    echo
    ok "UnitedSys ready."
    echo
    info "Run:  source ~/.bashrc   (or open a new terminal)"
    info "Then: usys register <file> <name>"
    echo
}

# ── usys register <file> <name> [description] ────────────────
cmd_register() {
    local src="${1:-}"
    local name="${2:-}"
    local desc="${3:-}"

    [[ -z "$src"  ]] && die "Usage: usys register <file> <name>"
    [[ -z "$name" ]] && die "Usage: usys register <file> <name>"
    [[ -f "$src"  ]] || die "File not found: $src"

    require_sqlite
    init_db 2>/dev/null || true

    # Resolve absolute path
    src="$(realpath "$src")"

    local filetype version hash size store_path

    filetype=$(detect_type "$src")
    version=$(next_version "$name")
    hash=$(file_hash "$src")
    size=$(wc -c < "$src")

    # Store a copy in versions dir
    local pkg_ver_dir="$USYS_VERSIONS/$name"
    mkdir -p "$pkg_ver_dir"
    store_path="$pkg_ver_dir/${version}_$(basename "$src")"
    cp "$src" "$store_path"
    chmod +x "$store_path" 2>/dev/null || true

    # Check if already registered — update or insert
    local exists
    exists=$(db "SELECT COUNT(*) FROM packages WHERE name='$name';")

    if [[ "$exists" -gt 0 ]]; then
        warn "'$name' already registered — use 'usys swap $name $src' to update"
        return 1
    fi

    # Register in DB
    db << SQL
INSERT INTO packages (name, current_ver, source_path, bin_path, filetype, description)
VALUES ('$name', '$version', '$src', '$USYS_BIN/$name', '$filetype', '$desc');

INSERT INTO versions (package, version, store_path, hash, size)
VALUES ('$name', '$version', '$store_path', '$hash', $size);

INSERT INTO swaplog (package, from_ver, to_ver, action, note)
VALUES ('$name', NULL, '$version', 'register', 'initial registration');
SQL

    # Create callable wrapper
    make_callable "$name" "$store_path" "$filetype"

    echo
    ok "Registered: ${BOLD}$name${RESET}"
    info "  Version  : $version"
    info "  Type     : $filetype"
    info "  Source   : $src"
    info "  Callable : usys call $name"
    info "  Direct   : $name  (once PATH is set)"
    echo
}

# ── usys call <name> [args...] ────────────────────────────────
cmd_call() {
    local name="${1:-}"
    [[ -z "$name" ]] && die "Usage: usys call <name> [args...]"
    shift || true

    require_sqlite

    local store_path
    store_path=$(db "
        SELECT v.store_path
        FROM packages p
        JOIN versions v ON v.package=p.name AND v.version=p.current_ver
        WHERE p.name='$name'
        LIMIT 1;
    ")

    [[ -z "$store_path" ]] && die "'$name' not found in registry. Run: usys list"
    [[ -f "$store_path" ]] || die "Stored file missing: $store_path"

    chmod +x "$store_path" 2>/dev/null || true
    exec "$store_path" "$@"
}

# ── usys swap <name> <newfile> [note] ─────────────────────────
cmd_swap() {
    local name="${1:-}"
    local src="${2:-}"
    local note="${3:-manual swap}"

    [[ -z "$name" ]] && die "Usage: usys swap <name> <newfile>"
    [[ -z "$src"  ]] && die "Usage: usys swap <name> <newfile>"
    [[ -f "$src"  ]] || die "File not found: $src"

    require_sqlite

    local exists
    exists=$(db "SELECT COUNT(*) FROM packages WHERE name='$name';")
    [[ "$exists" -eq 0 ]] && die "'$name' not registered. Run: usys register $src $name"

    src="$(realpath "$src")"

    local old_ver filetype version hash size store_path

    old_ver=$(db "SELECT current_ver FROM packages WHERE name='$name';")
    filetype=$(detect_type "$src")
    version=$(next_version "$name")
    hash=$(file_hash "$src")
    size=$(wc -c < "$src")

    local pkg_ver_dir="$USYS_VERSIONS/$name"
    mkdir -p "$pkg_ver_dir"
    store_path="$pkg_ver_dir/${version}_$(basename "$src")"
    cp "$src" "$store_path"
    chmod +x "$store_path" 2>/dev/null || true

    db << SQL
INSERT INTO versions (package, version, store_path, hash, size, note)
VALUES ('$name', '$version', '$store_path', '$hash', $size, '$note');

UPDATE packages
SET current_ver='$version',
    source_path='$src',
    filetype='$filetype',
    updated=datetime('now')
WHERE name='$name';

INSERT INTO swaplog (package, from_ver, to_ver, action, note)
VALUES ('$name', '$old_ver', '$version', 'swap', '$note');
SQL

    # Regenerate wrapper (points to new version via DB lookup)
    make_callable "$name" "$store_path" "$filetype"

    echo
    ok "Hotswapped: ${BOLD}$name${RESET}"
    info "  $old_ver  →  $version"
    info "  Source : $src"
    info "  Note   : $note"
    echo
    ok "Live. No restart needed."
    echo
}

# ── usys rollback <name> [version] ───────────────────────────
cmd_rollback() {
    local name="${1:-}"
    local target_ver="${2:-}"

    [[ -z "$name" ]] && die "Usage: usys rollback <name> [version]"

    require_sqlite

    local exists
    exists=$(db "SELECT COUNT(*) FROM packages WHERE name='$name';")
    [[ "$exists" -eq 0 ]] && die "'$name' not registered"

    local current_ver
    current_ver=$(db "SELECT current_ver FROM packages WHERE name='$name';")

    if [[ -z "$target_ver" ]]; then
        # Roll back to previous version
        target_ver=$(db "
            SELECT version FROM versions
            WHERE package='$name' AND version != '$current_ver'
            ORDER BY id DESC LIMIT 1;
        ")
        [[ -z "$target_ver" ]] && die "No previous version to roll back to"
    fi

    local store_path
    store_path=$(db "
        SELECT store_path FROM versions
        WHERE package='$name' AND version='$target_ver'
        LIMIT 1;
    ")

    [[ -z "$store_path" ]] && die "Version '$target_ver' not found for '$name'"
    [[ -f "$store_path" ]] || die "Stored file missing: $store_path"

    db << SQL
UPDATE packages
SET current_ver='$target_ver', updated=datetime('now')
WHERE name='$name';

INSERT INTO swaplog (package, from_ver, to_ver, action, note)
VALUES ('$name', '$current_ver', '$target_ver', 'rollback', 'manual rollback');
SQL

    make_callable "$name" "$store_path" ""

    echo
    ok "Rolled back: ${BOLD}$name${RESET}"
    info "  $current_ver  →  $target_ver"
    echo
    ok "Live. No restart needed."
    echo
}

# ── usys list ────────────────────────────────────────────────
cmd_list() {
    require_sqlite

    local count
    count=$(db "SELECT COUNT(*) FROM packages;")

    echo
    echo -e "${BOLD}  UnitedSys Registry  —  $count package(s)${RESET}"
    echo "  ─────────────────────────────────────────────────"
    printf "  %-20s %-8s %-10s  %s\n" "NAME" "VERSION" "TYPE" "UPDATED"
    echo "  ─────────────────────────────────────────────────"

    db -separator "|" \
       "SELECT name, current_ver, filetype, updated FROM packages ORDER BY name;" \
    | while IFS="|" read -r name ver ftype updated; do
        printf "  ${GREEN}%-20s${RESET} %-8s %-10s  %s\n" \
            "$name" "$ver" "$ftype" "$updated"
    done

    echo "  ─────────────────────────────────────────────────"
    echo
}

# ── usys info <name> ─────────────────────────────────────────
cmd_info() {
    local name="${1:-}"
    [[ -z "$name" ]] && die "Usage: usys info <name>"

    require_sqlite

    local exists
    exists=$(db "SELECT COUNT(*) FROM packages WHERE name='$name';")
    [[ "$exists" -eq 0 ]] && die "'$name' not in registry"

    echo
    echo -e "${BOLD}  $name${RESET}"
    echo "  ─────────────────────────────────────────────"

    db -separator "|" \
       "SELECT current_ver, filetype, source_path, registered, updated, description
        FROM packages WHERE name='$name';" \
    | while IFS="|" read -r ver ftype src reg upd desc; do
        echo -e "  ${CYAN}Current version${RESET}  : $ver"
        echo -e "  ${CYAN}Type${RESET}             : $ftype"
        echo -e "  ${CYAN}Original source${RESET}  : $src"
        echo -e "  ${CYAN}Registered${RESET}       : $reg"
        echo -e "  ${CYAN}Last updated${RESET}     : $upd"
        [[ -n "$desc" ]] && echo -e "  ${CYAN}Description${RESET}      : $desc"
    done

    echo
    echo -e "  ${BOLD}Version history:${RESET}"
    echo "  ─────────────────────────────────────────────"
    printf "  %-8s  %-12s  %-8s  %s\n" "VERSION" "CREATED" "SIZE" "HASH"
    echo "  ─────────────────────────────────────────────"

    db -separator "|" \
       "SELECT version, created, size, hash, note
        FROM versions WHERE package='$name' ORDER BY id DESC;" \
    | while IFS="|" read -r ver created size hash note; do
        local current
        current=$(db "SELECT current_ver FROM packages WHERE name='$name';")
        local marker=""
        [[ "$ver" == "$current" ]] && marker="${GREEN} ◄ current${RESET}"
        printf "  %-8s  %-12s  %-8s  %s\n" \
            "$ver" "${created:0:10}" "${size}b" "${hash:0:12}..."
        echo -e "           ${marker}${note:+  note: $note}"
    done

    echo
    echo -e "  ${BOLD}Swap log:${RESET}"
    echo "  ─────────────────────────────────────────────"

    db -separator "|" \
       "SELECT ts, action, from_ver, to_ver, note
        FROM swaplog WHERE package='$name' ORDER BY id DESC LIMIT 10;" \
    | while IFS="|" read -r ts action from to note; do
        printf "  %-12s  %-10s  %s → %s\n" \
            "${ts:0:10}" "$action" "${from:----}" "${to:----}"
    done

    echo
}

# ── usys remove <name> ───────────────────────────────────────
cmd_remove() {
    local name="${1:-}"
    [[ -z "$name" ]] && die "Usage: usys remove <name>"

    require_sqlite

    local exists
    exists=$(db "SELECT COUNT(*) FROM packages WHERE name='$name';")
    [[ "$exists" -eq 0 ]] && die "'$name' not in registry"

    echo
    warn "This will remove '$name' from the registry."
    warn "Stored versions in $USYS_VERSIONS/$name will be kept."
    read -rp "  Continue? [y/N] " confirm
    [[ "$confirm" =~ ^[Yy]$ ]] || { info "Cancelled."; exit 0; }

    db "DELETE FROM packages WHERE name='$name';"
    rm -f "$USYS_BIN/$name"

    ok "Removed: $name"
    info "Version history kept at: $USYS_VERSIONS/$name"
    echo
}

# ── usys where <name> ────────────────────────────────────────
cmd_where() {
    local name="${1:-}"
    [[ -z "$name" ]] && die "Usage: usys where <name>"

    require_sqlite

    local store_path source_path
    store_path=$(db "
        SELECT v.store_path
        FROM packages p
        JOIN versions v ON v.package=p.name AND v.version=p.current_ver
        WHERE p.name='$name' LIMIT 1;
    ")
    source_path=$(db "SELECT source_path FROM packages WHERE name='$name';")

    [[ -z "$store_path" ]] && die "'$name' not in registry"

    echo
    info "  Name          : $name"
    info "  Callable      : $USYS_BIN/$name"
    info "  Stored version: $store_path"
    info "  Original source: $source_path"
    echo
}

# ── usys sync <name> <dest> ───────────────────────────────────
cmd_sync() {
    local name="${1:-}"
    local dest="${2:-}"

    [[ -z "$name" ]] && die "Usage: usys sync <name> <dest>"
    [[ -z "$dest" ]] && die "Usage: usys sync <name> <dest>"

    require_sqlite

    local store_path
    store_path=$(db "
        SELECT v.store_path
        FROM packages p
        JOIN versions v ON v.package=p.name AND v.version=p.current_ver
        WHERE p.name='$name' LIMIT 1;
    ")

    [[ -z "$store_path" ]] && die "'$name' not in registry"

    mkdir -p "$(dirname "$dest")"
    rsync -av "$store_path" "$dest" 2>/dev/null || \
        cp -v "$store_path" "$dest"

    ok "Synced: $name → $dest"
}

# ── usys clone <name> <dest> ──────────────────────────────────
cmd_clone() {
    local name="${1:-}"
    local dest="${2:-}"

    [[ -z "$name" ]] && die "Usage: usys clone <name> <dest>"
    [[ -z "$dest" ]] && die "Usage: usys clone <name> <dest>"

    require_sqlite

    local exists
    exists=$(db "SELECT COUNT(*) FROM packages WHERE name='$name';")
    [[ "$exists" -eq 0 ]] && die "'$name' not in registry"

    # Clone full version history to destination
    local src_dir="$USYS_VERSIONS/$name"
    local dest_dir="$dest/$name"

    mkdir -p "$dest_dir"
    cp -r "$src_dir/." "$dest_dir/"

    # Export DB record for this package
    db << SQL > "$dest_dir/usys_export.sql"
SELECT '-- UnitedSys export: $name';
SELECT '-- Generated: ' || datetime('now');
SELECT '-- usys import to restore';
SQL

    db -separator "|" \
       "SELECT * FROM packages WHERE name='$name';" \
       >> "$dest_dir/usys_export.sql"

    db -separator "|" \
       "SELECT * FROM versions WHERE package='$name';" \
       >> "$dest_dir/usys_export.sql"

    ok "Cloned: $name → $dest_dir"
    info "Full version history included"
    info "To restore: usys import $dest_dir/usys_export.sql"
}

# ── usys search <query> ───────────────────────────────────────
cmd_search() {
    local query="${1:-}"
    [[ -z "$query" ]] && die "Usage: usys search <query>"

    require_sqlite

    echo
    echo -e "${BOLD}  Search results for: $query${RESET}"
    echo "  ────────────────────────────────────────────"

    db -separator "|" \
       "SELECT name, current_ver, filetype, description
        FROM packages
        WHERE name LIKE '%$query%'
           OR description LIKE '%$query%'
           OR filetype LIKE '%$query%'
        ORDER BY name;" \
    | while IFS="|" read -r name ver ftype desc; do
        printf "  ${GREEN}%-20s${RESET} %-8s %-10s  %s\n" \
            "$name" "$ver" "$ftype" "$desc"
    done

    echo
}

# ── usys version ─────────────────────────────────────────────
cmd_version() {
    echo "usys $USYS_VERSION — UnitedSys universal hotswap registry"
    echo "GPL v3 — https://github.com/jwl247/unitedsys"
}

# ============================================================
#  DISPATCH
# ============================================================

CMD="${1:-}"
shift 2>/dev/null || true

case "$CMD" in
    init)       cmd_init ;;
    register)   check_sudo; cmd_register "$@" ;;
    call)       cmd_call "$@" ;;
    swap)       check_sudo; cmd_swap "$@" ;;
    rollback)   check_sudo; cmd_rollback "$@" ;;
    list|ls)    cmd_list ;;
    info)       cmd_info "$@" ;;
    remove|rm)  check_sudo; cmd_remove "$@" ;;
    where)      cmd_where "$@" ;;
    sync)       cmd_sync "$@" ;;
    clone)      cmd_clone "$@" ;;
    search)     cmd_search "$@" ;;
    version|-v) cmd_version ;;

    ""|help|--help|-h)
        echo
        echo -e "${BOLD}  UnitedSys (usys) v${USYS_VERSION}${RESET}"
        echo -e "  Universal file registration, versioning, and hotswap"
        echo
        echo -e "  ${CYAN}Usage:${RESET}"
        echo "    usys init                         first time setup"
        echo "    usys register <file> <name>       register a file"
        echo "    usys call <name> [args...]         call by name"
        echo "    usys swap <name> <newfile>         hotswap live"
        echo "    usys rollback <name> [version]     roll back"
        echo "    usys list                          list all"
        echo "    usys info <name>                   version history"
        echo "    usys remove <name>                 unregister"
        echo "    usys where <name>                  show location"
        echo "    usys sync <name> <dest>            sync to dest"
        echo "    usys clone <name> <dest>           clone with history"
        echo "    usys search <query>                search registry"
        echo "    usys version                       show version"
        echo
        echo -e "  ${CYAN}Examples:${RESET}"
        echo "    usys register ./intake.sh intake"
        echo "    usys call intake"
        echo "    usys swap intake ./intake_v2.sh"
        echo "    usys rollback intake v1"
        echo "    usys clone intake /media/jwl247/breach_coms2/backup"
        echo
        ;;

    *)
        # Try calling it as a registered package name directly
        # This allows: usys intake  instead of  usys call intake
        if sqlite3 "$USYS_DB" \
           "SELECT COUNT(*) FROM packages WHERE name='$CMD';" \
           2>/dev/null | grep -q "^1$"; then
            cmd_call "$CMD" "$@"
        else
            err "Unknown command: $CMD"
            echo "Run 'usys help' for usage"
            exit 1
        fi
        ;;
esac
