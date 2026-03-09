#!/usr/bin/env bash
# ============================================================
#  install_phoenix_grub.sh
#  Installs the Phoenix master boot controller to a dedicated
#  partition that survives OS reinstalls
#
#  Usage: sudo ./install_phoenix_grub.sh [GRUB_DEVICE]
#  Example: sudo ./install_phoenix_grub.sh /dev/sde
#
#  What it does:
#  1. Installs GRUB to the target device's MBR/EFI
#  2. Copies grub.cfg to the GRUB partition
#  3. Sets this GRUB as the primary boot manager via efibootmgr
#  4. All other distros chain through this menu — never bypass it
# ============================================================

set -euo pipefail

GRUB_DEVICE="${1:-/dev/sde}"
GRUB_CFG_SRC="$(dirname "$0")/grub.cfg"
GRUB_MOUNT="/tmp/phoenix_grub_mount"
GRUB_DIR="$GRUB_MOUNT/boot/grub"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info() { echo -e "${CYAN}[INFO]${RESET} $*"; }
ok()   { echo -e "${GREEN}[OK]${RESET}   $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET} $*"; }
die()  { echo -e "${RED}[FATAL]${RESET} $*"; exit 1; }

[[ $EUID -ne 0 ]] && die "Must run as root"
[[ -b "$GRUB_DEVICE" ]] || die "Device $GRUB_DEVICE not found"
[[ -f "$GRUB_CFG_SRC" ]] || die "grub.cfg not found at $GRUB_CFG_SRC"

echo -e "${BOLD}╔══════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║   PHOENIX GRUB INSTALLER  //  Phoenix-DevOps ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════╝${RESET}"
echo

info "Target device : $GRUB_DEVICE"
info "GRUB config   : $GRUB_CFG_SRC"
echo

# ── Detect EFI or BIOS ───────────────────────────────────────
if [[ -d /sys/firmware/efi ]]; then
    BOOT_MODE="uefi"
    info "Boot mode: UEFI"
else
    BOOT_MODE="bios"
    info "Boot mode: BIOS/Legacy"
fi

# ── Find or create GRUB partition ────────────────────────────
info "Scanning $GRUB_DEVICE for existing EFI/boot partition..."

# Look for existing EFI partition on this device
EFI_PART=$(fdisk -l "$GRUB_DEVICE" 2>/dev/null | \
    awk '/EFI System/{print $1}' | head -1)

BOOT_PART=$(fdisk -l "$GRUB_DEVICE" 2>/dev/null | \
    awk '/Linux/{print $1}' | head -1)

if [[ -n "$EFI_PART" && "$BOOT_MODE" == "uefi" ]]; then
    GRUB_PART="$EFI_PART"
    ok "Found EFI partition: $GRUB_PART"
elif [[ -n "$BOOT_PART" ]]; then
    GRUB_PART="$BOOT_PART"
    ok "Found boot partition: $GRUB_PART"
else
    warn "No suitable partition found on $GRUB_DEVICE"
    warn "You may need to create one first with fdisk/parted"
    warn "Recommended: 512M EFI partition at start of drive"
    echo
    read -rp "Continue anyway and install to MBR only? [y/N] " confirm
    [[ "$confirm" =~ ^[Yy]$ ]] || exit 1
    GRUB_PART=""
fi

# ── Mount and install ─────────────────────────────────────────
if [[ -n "${GRUB_PART:-}" ]]; then
    mkdir -p "$GRUB_MOUNT"
    mount "$GRUB_PART" "$GRUB_MOUNT" 2>/dev/null || \
        mount -t vfat "$GRUB_PART" "$GRUB_MOUNT"
    ok "Mounted $GRUB_PART → $GRUB_MOUNT"
fi

mkdir -p "$GRUB_DIR"

# ── Install GRUB ──────────────────────────────────────────────
info "Installing GRUB to $GRUB_DEVICE ..."

if [[ "$BOOT_MODE" == "uefi" ]]; then
    grub2-install \
        --target=x86_64-efi \
        --efi-directory="$GRUB_MOUNT" \
        --bootloader-id="Phoenix-DevOps" \
        --recheck \
        "$GRUB_DEVICE" || \
    grub-install \
        --target=x86_64-efi \
        --efi-directory="$GRUB_MOUNT" \
        --bootloader-id="Phoenix-DevOps" \
        --recheck \
        "$GRUB_DEVICE"
else
    grub2-install --recheck "$GRUB_DEVICE" || \
    grub-install --recheck "$GRUB_DEVICE"
fi

ok "GRUB installed"

# ── Copy our custom grub.cfg ──────────────────────────────────
info "Installing Phoenix grub.cfg..."

# Find where GRUB put its files
GRUB_INSTALL_DIR=$(find "$GRUB_MOUNT" -name "grub.cfg" 2>/dev/null | \
    head -1 | xargs dirname 2>/dev/null || echo "$GRUB_DIR")

cp "$GRUB_CFG_SRC" "$GRUB_INSTALL_DIR/grub.cfg"
ok "grub.cfg installed → $GRUB_INSTALL_DIR/grub.cfg"

# ── Set as primary boot entry ─────────────────────────────────
if [[ "$BOOT_MODE" == "uefi" ]] && command -v efibootmgr &>/dev/null; then
    info "Setting Phoenix-DevOps as primary boot entry..."

    # Find our new entry
    BOOT_ENTRY=$(efibootmgr -v | grep "Phoenix-DevOps" | \
        awk '{print $1}' | sed 's/Boot//;s/\*//' | head -1)

    if [[ -n "$BOOT_ENTRY" ]]; then
        efibootmgr -o "$BOOT_ENTRY" 2>/dev/null || \
        efibootmgr --bootorder "$BOOT_ENTRY" 2>/dev/null || true
        ok "Boot order updated — Phoenix-DevOps is first"
    else
        warn "Could not find Phoenix-DevOps in EFI entries — set boot order manually"
        warn "Run: efibootmgr -v  to see current entries"
    fi
fi

# ── Cleanup ───────────────────────────────────────────────────
if [[ -n "${GRUB_PART:-}" ]]; then
    umount "$GRUB_MOUNT" 2>/dev/null || true
    rmdir "$GRUB_MOUNT" 2>/dev/null || true
fi

# ── Summary ───────────────────────────────────────────────────
echo
echo -e "${BOLD}══════════════════════════════════════════════${RESET}"
echo -e "  ${GREEN}Phoenix GRUB installed successfully${RESET}"
echo -e "  Device    : $GRUB_DEVICE"
echo -e "  Boot mode : $BOOT_MODE"
echo -e "  Config    : $GRUB_INSTALL_DIR/grub.cfg"
echo
echo -e "  ${CYAN}Every boot will now stop at the Phoenix menu.${RESET}"
echo -e "  ${CYAN}Add new distros by editing grub.cfg.${RESET}"
echo -e "${BOLD}══════════════════════════════════════════════${RESET}"
echo

# ── Reminder: update grub.cfg UUIDs ──────────────────────────
echo -e "${YELLOW}NOTE: Update UUIDs in grub.cfg to match your drives:${RESET}"
echo
lsblk -o NAME,SIZE,FSTYPE,UUID,LABEL 2>/dev/null | grep -v "^loop"
echo
echo "Edit: $GRUB_INSTALL_DIR/grub.cfg"
