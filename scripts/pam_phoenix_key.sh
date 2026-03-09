#!/usr/bin/env bash
# ============================================================
#  pam_phoenix_key.sh  —  Phoenix USB Key PAM Auth
#  Called by pam_exec.so for: sudo, login, sshd
#
#  Returns 0  → key valid    → auth succeeds (no password)
#  Returns 1  → key missing  → auth denied
#
#  Usage in /etc/pam.d/*:
#    auth [success=done default=die] pam_exec.so \
#         /home/jwl247/phoenix/scripts/pam_phoenix_key.sh
# ============================================================

set -uo pipefail

KEY_HASH_FILE="/home/jwl247/phoenix/keys/key.hash"
KEY_FILENAME=".phoenix_key"
KEY_LABEL="PHOENIX-KEY"
LOG_FILE="/var/log/phoenix_auth.log"
TMP_MOUNT="/tmp/.phoenix_pam_$$"

# ── Logging ──────────────────────────────────────────────────
log() {
    local level="$1"; shift
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$level] service=${PAM_SERVICE:-?} user=${PAM_USER:-?} tty=${PAM_TTY:-?} $*" \
        >> "$LOG_FILE" 2>/dev/null || true
}

# ── Load expected hash ───────────────────────────────────────
if [[ ! -f "$KEY_HASH_FILE" ]]; then
    log "FAIL" "key.hash not found at $KEY_HASH_FILE"
    exit 1
fi

EXPECTED=$(tr -d '[:space:]' < "$KEY_HASH_FILE")

if [[ -z "$EXPECTED" ]]; then
    log "FAIL" "key.hash is empty"
    exit 1
fi

# ── Key check function ───────────────────────────────────────
check_dir() {
    local dir="$1"
    local keyfile="$dir/$KEY_FILENAME"
    [[ -f "$keyfile" ]] || return 1
    local actual
    actual=$(tr -d '[:space:]' < "$keyfile" 2>/dev/null) || return 1
    [[ "$actual" == "$EXPECTED" ]]
}

# ── 1. Scan already-mounted filesystems ──────────────────────
while IFS= read -r mountpoint; do
    if check_dir "$mountpoint"; then
        log "OK" "key matched at $mountpoint"
        exit 0
    fi
done < <(awk '{print $2}' /proc/mounts 2>/dev/null)

# ── 2. Try to find PHOENIX-KEY by label and mount it ─────────
LABEL_DEV="/dev/disk/by-label/$KEY_LABEL"

if [[ -L "$LABEL_DEV" ]]; then
    mkdir -p "$TMP_MOUNT"
    if mount -o ro "$LABEL_DEV" "$TMP_MOUNT" 2>/dev/null; then
        if check_dir "$TMP_MOUNT"; then
            log "OK" "key matched via label mount ($LABEL_DEV)"
            umount "$TMP_MOUNT" 2>/dev/null
            rmdir  "$TMP_MOUNT" 2>/dev/null
            exit 0
        fi
        umount "$TMP_MOUNT" 2>/dev/null
    fi
    rmdir "$TMP_MOUNT" 2>/dev/null
fi

# ── 3. Fallback: scan removable block devices ─────────────────
for dev in /dev/sd?1 /dev/mmcblk?p1; do
    [[ -b "$dev" ]] || continue
    mkdir -p "$TMP_MOUNT"
    if mount -o ro "$dev" "$TMP_MOUNT" 2>/dev/null; then
        if check_dir "$TMP_MOUNT"; then
            log "OK" "key matched via device scan ($dev)"
            umount "$TMP_MOUNT" 2>/dev/null
            rmdir  "$TMP_MOUNT" 2>/dev/null
            exit 0
        fi
        umount "$TMP_MOUNT" 2>/dev/null
    fi
done
rmdir "$TMP_MOUNT" 2>/dev/null || true

log "FAIL" "key not found on any device"
exit 1
