#!/usr/bin/env bash
# ============================================================
#  gen_key.sh  —  Phoenix GRUB USB Key Generator
#  Run once to initialize a USB as the boot key
#  Usage: sudo ./gen_key.sh /dev/sdX
# ============================================================

set -euo pipefail

TARGET="${1:-}"
KEY_DIR="/tmp/phoenix_key_mount"
KEY_FILENAME=".phoenix_key"          # hidden file on USB
KEY_HASH_FILE="$(dirname "$0")/../keys/key.hash"
KEY_ID_FILE="$(dirname "$0")/../keys/key.id"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info() { echo -e "${CYAN}[INFO]${RESET} $*"; }
ok()   { echo -e "${GREEN}[OK]${RESET}   $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET} $*"; }
die()  { echo -e "${RED}[FATAL]${RESET} $*"; exit 1; }

[[ $EUID -ne 0 ]] && die "Must run as root"
[[ -z "$TARGET" ]] && die "Usage: $0 /dev/sdX"
[[ -b "$TARGET" ]] || die "Device $TARGET not found"

echo -e "${BOLD}╔══════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║     PHOENIX USB KEY GENERATOR                ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════╝${RESET}"
echo

# Show drive info before doing anything
info "Target USB: $TARGET"
lsblk "$TARGET" 2>/dev/null || true
echo
warn "This will write a keyfile to $TARGET"
warn "It will NOT erase the drive — keyfile is hidden alongside existing data"
echo
read -rp "Continue? [y/N] " confirm
[[ "$confirm" =~ ^[Yy]$ ]] || exit 0

# ── Find the first partition ──────────────────────────────────
PART=$(lsblk -lnpo NAME,TYPE "$TARGET" | awk '$2=="part"{print $1}' | head -1)
[[ -z "$PART" ]] && PART="$TARGET"

info "Writing to partition: $PART"

# ── Mount USB ─────────────────────────────────────────────────
mkdir -p "$KEY_DIR"
mount "$PART" "$KEY_DIR" 2>/dev/null || \
mount -t vfat "$PART" "$KEY_DIR" 2>/dev/null || \
die "Could not mount $PART"

# ── Generate unique key ───────────────────────────────────────
# Key = machine UUID + timestamp + random bytes — unique per installation
MACHINE_ID=$(cat /etc/machine-id 2>/dev/null || echo "unknown")
TIMESTAMP=$(date +%s%N)
RANDOM_BYTES=$(dd if=/dev/urandom bs=64 count=1 2>/dev/null | base64 -w0)

KEY_DATA="${MACHINE_ID}:${TIMESTAMP}:${RANDOM_BYTES}"
KEY_HASH=$(echo "$KEY_DATA" | sha256sum | awk '{print $1}')
KEY_ID=$(echo "$KEY_DATA" | md5sum | awk '{print $1}')

# Write hidden keyfile to USB
echo "$KEY_HASH" > "$KEY_DIR/$KEY_FILENAME"
chmod 600 "$KEY_DIR/$KEY_FILENAME" 2>/dev/null || true

ok "Keyfile written to USB: $KEY_DIR/$KEY_FILENAME"

# ── Save hash locally for GRUB to verify ─────────────────────
mkdir -p "$(dirname "$KEY_HASH_FILE")"
echo "$KEY_HASH" > "$KEY_HASH_FILE"
echo "$KEY_ID"   > "$KEY_ID_FILE"

ok "Key hash saved: $KEY_HASH_FILE"
ok "Key ID saved  : $KEY_ID_FILE"

# ── Also write key hash into grub.cfg template ────────────────
GRUB_CFG="$(dirname "$0")/../grub/grub.cfg"
if [[ -f "$GRUB_CFG" ]]; then
    # Replace the placeholder with the real hash
    sed -i "s|PHOENIX_KEY_HASH_PLACEHOLDER|$KEY_HASH|g" "$GRUB_CFG"
    ok "Key hash injected into grub.cfg"
fi

umount "$KEY_DIR" 2>/dev/null || true
rmdir  "$KEY_DIR" 2>/dev/null || true

echo
echo -e "${BOLD}══════════════════════════════════════════════${RESET}"
echo -e "  ${GREEN}USB key initialized successfully${RESET}"
echo -e "  Key ID   : ${CYAN}$KEY_ID${RESET}"
echo -e "  Key hash : ${CYAN}${KEY_HASH:0:16}...${RESET}"
echo -e ""
echo -e "  ${YELLOW}Guard this USB — it is the only key to your boot controller${RESET}"
echo -e "  ${YELLOW}Run gen_key.sh again on a second USB for a backup key${RESET}"
echo -e "${BOLD}══════════════════════════════════════════════${RESET}"
echo
