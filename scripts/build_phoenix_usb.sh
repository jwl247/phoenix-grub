#!/usr/bin/env bash
# ============================================================
#  build_phoenix_usb.sh
#  Builds the Phoenix GRUB memdisk image and writes it to USB
#
#  What it does:
#  1. Packages grub.cfg + key logic into a memdisk image
#  2. Builds a GRUB EFI/BIOS image that loads itself to RAM
#  3. Writes the whole thing to a USB drive
#  4. USB boots → GRUB loads to RAM → USB can be pulled
#
#  Usage: sudo ./build_phoenix_usb.sh /dev/sdX
# ============================================================

set -euo pipefail

TARGET="${1:-}"
WORK_DIR="/tmp/phoenix_usb_build"
GRUB_DIR="$(dirname "$0")/../grub"
SCRIPTS_DIR="$(dirname "$0")"
KEY_LABEL="PHOENIX-KEY"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info() { echo -e "${CYAN}[INFO]${RESET} $*"; }
ok()   { echo -e "${GREEN}[OK]${RESET}   $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET} $*"; }
die()  { echo -e "${RED}[FATAL]${RESET} $*"; exit 1; }

[[ $EUID -ne 0 ]] && die "Must run as root"
[[ -z "$TARGET" ]] && die "Usage: $0 /dev/sdX"
[[ -b "$TARGET" ]] || die "Device $TARGET not found"

echo -e "${BOLD}╔══════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║     PHOENIX USB BOOT KEY BUILDER                 ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════╝${RESET}"
echo

info "Target USB : $TARGET"
lsblk "$TARGET"
echo
warn "This will ERASE $TARGET and build the Phoenix boot key"
echo
read -rp "Continue? [y/N] " confirm
[[ "$confirm" =~ ^[Yy]$ ]] || exit 0

# ── Check dependencies ────────────────────────────────────────
for cmd in grub-install grub2-install grub-mkimage grub2-mkimage \
           mkfs.vfat parted dd; do
    command -v "$cmd" &>/dev/null && continue
    # check alternate name
    true
done

# Detect grub command
if command -v grub2-install &>/dev/null; then
    GRUB_INSTALL="grub2-install"
    GRUB_MKIMAGE="grub2-mkimage"
    GRUB_DIR_PREFIX="/usr/lib/grub"
elif command -v grub-install &>/dev/null; then
    GRUB_INSTALL="grub-install"
    GRUB_MKIMAGE="grub-mkimage"
    GRUB_DIR_PREFIX="/usr/lib/grub"
else
    die "grub-install not found. Install: apt install grub2-common OR dnf install grub2-tools"
fi

# ── Partition the USB ─────────────────────────────────────────
info "Partitioning $TARGET ..."

# Wipe and create GPT with single FAT32 partition
parted -s "$TARGET" mklabel gpt
parted -s "$TARGET" mkpart primary fat32 1MiB 100%
parted -s "$TARGET" set 1 esp on
parted -s "$TARGET" set 1 boot on

# Give kernel a moment to register new partition table
sleep 1
partprobe "$TARGET" 2>/dev/null || true
sleep 1

# Find the partition
PART="${TARGET}1"
[[ -b "$PART" ]] || PART="${TARGET}p1"
[[ -b "$PART" ]] || die "Could not find partition on $TARGET"

ok "Partition: $PART"

# ── Format ────────────────────────────────────────────────────
info "Formatting $PART as FAT32 (label: $KEY_LABEL) ..."
mkfs.vfat -F32 -n "$KEY_LABEL" "$PART"
ok "Formatted"

# ── Mount ─────────────────────────────────────────────────────
mkdir -p "$WORK_DIR/usb"
mount "$PART" "$WORK_DIR/usb"
ok "Mounted $PART → $WORK_DIR/usb"

# ── Install GRUB to USB ───────────────────────────────────────
info "Installing GRUB to USB ..."

mkdir -p "$WORK_DIR/usb/boot/grub"
mkdir -p "$WORK_DIR/usb/EFI/BOOT"

# GRUB modules to embed — everything we need for the menu
GRUB_MODULES="
    all_video
    btrfs
    cat
    chain
    configfile
    echo
    ext2
    fat
    gcry_sha256
    gcry_sha512
    gfxmenu
    gfxterm
    gfxterm_background
    halt
    hashsum
    http
    linux
    loadenv
    lvm
    memdisk
    minicmd
    normal
    ntfs
    part_gpt
    part_msdos
    password_pbkdf2
    probe
    regexp
    reboot
    search
    search_fs_label
    search_fs_uuid
    search_label
    sleep
    tar
    test
    true
    video
    xfs
"

GRUB_MODULES_FLAT=$(echo $GRUB_MODULES | tr '\n' ' ')

# Build EFI image (UEFI boot)
if [[ -d "$GRUB_DIR_PREFIX/x86_64-efi" ]]; then
    info "Building EFI image..."
    $GRUB_MKIMAGE \
        --directory "$GRUB_DIR_PREFIX/x86_64-efi" \
        --prefix "(memdisk)/boot/grub" \
        --output "$WORK_DIR/usb/EFI/BOOT/BOOTX64.EFI" \
        --format x86_64-efi \
        --compression auto \
        --memdisk "$WORK_DIR/memdisk.tar" \
        $GRUB_MODULES_FLAT 2>/dev/null || \
    $GRUB_MKIMAGE \
        --directory "$GRUB_DIR_PREFIX/x86_64-efi" \
        --prefix "/boot/grub" \
        --output "$WORK_DIR/usb/EFI/BOOT/BOOTX64.EFI" \
        --format x86_64-efi \
        $GRUB_MODULES_FLAT 2>/dev/null || \
    warn "EFI image build failed — BIOS only"
    ok "EFI image built"
fi

# Build BIOS image (legacy boot)
if [[ -d "$GRUB_DIR_PREFIX/i386-pc" ]]; then
    info "Building BIOS/MBR image..."
    $GRUB_INSTALL \
        --target=i386-pc \
        --boot-directory="$WORK_DIR/usb/boot" \
        --recheck \
        "$TARGET" 2>/dev/null || warn "BIOS install failed — EFI only"
    ok "BIOS image built"
fi

# ── Build memdisk tar ─────────────────────────────────────────
# This is what gets loaded into RAM — the entire GRUB config
info "Building memdisk (RAM image)..."

mkdir -p "$WORK_DIR/memdisk/boot/grub"

# Copy our custom grub.cfg
cp "$GRUB_DIR/grub.cfg" "$WORK_DIR/memdisk/boot/grub/grub.cfg"

# Copy GRUB modules into memdisk so they're available from RAM
if [[ -d "$GRUB_DIR_PREFIX/x86_64-efi" ]]; then
    cp -r "$GRUB_DIR_PREFIX/x86_64-efi" \
       "$WORK_DIR/memdisk/boot/grub/" 2>/dev/null || true
fi

# Build the tar archive GRUB will load as memdisk
tar -C "$WORK_DIR/memdisk" -cf "$WORK_DIR/memdisk.tar" .
ok "Memdisk image: $(du -h $WORK_DIR/memdisk.tar | awk '{print $1}')"

# ── Copy grub.cfg to USB too (fallback if memdisk fails) ─────
cp "$GRUB_DIR/grub.cfg" "$WORK_DIR/usb/boot/grub/grub.cfg"

# ── Copy install script to USB ────────────────────────────────
# So "Install GRUB to disk" menu entry can find it
cp "$SCRIPTS_DIR/install_phoenix_grub.sh" \
   "$WORK_DIR/usb/install_phoenix_grub.sh" 2>/dev/null || true

# ── Write a boot.cfg that loads to RAM then pulls USB ─────────
cat > "$WORK_DIR/usb/boot/grub/load_to_ram.cfg" << 'RAMCFG'
# Load everything to RAM, then continue from memdisk
# This allows the USB to be removed after boot

insmod memdisk
insmod tar

echo "Phoenix GRUB loading to RAM..."
echo "You may remove the USB after the menu appears."
sleep 2

# Load the memdisk image into RAM
memdisk --mem /boot/grub/memdisk.tar

# Switch root to memdisk and load config from RAM
set root=(memdisk)
set prefix=(memdisk)/boot/grub
configfile (memdisk)/boot/grub/grub.cfg
RAMCFG

# Copy memdisk.tar to USB so GRUB can load it into RAM
cp "$WORK_DIR/memdisk.tar" "$WORK_DIR/usb/boot/grub/memdisk.tar"
ok "Memdisk tar copied to USB"

# ── Set primary grub.cfg to load-to-RAM sequence ─────────────
cat > "$WORK_DIR/usb/boot/grub/grub.cfg" << 'BOOTCFG'
# Phoenix GRUB — Initial loader
# Loads full config to RAM, then runs from memory

set timeout=3
set timeout_style=countdown

insmod memdisk
insmod tar
insmod all_video
insmod gfxterm
terminal_output gfxterm

echo ""
echo "  PHOENIX-DEVOPS-oS  Boot Controller"
echo "  Loading to RAM..."
echo ""

# Copy self to RAM
if [ -f /boot/grub/memdisk.tar ]; then
    memdisk --mem /boot/grub/memdisk.tar
    set root=(memdisk)
    set prefix=(memdisk)/boot/grub
    insmod (memdisk)/boot/grub/x86_64-efi/normal.mod
    configfile (memdisk)/boot/grub/grub.cfg
else
    # Fallback — run directly from USB
    configfile /boot/grub/grub.cfg
fi
BOOTCFG

# ── Cleanup ───────────────────────────────────────────────────
umount "$WORK_DIR/usb" 2>/dev/null || true
rm -rf "$WORK_DIR" 2>/dev/null || true

echo
echo -e "${BOLD}══════════════════════════════════════════════════${RESET}"
echo -e "  ${GREEN}Phoenix USB Boot Key built successfully${RESET}"
echo -e ""
echo -e "  Device : $TARGET  ($PART)"
echo -e "  Label  : $KEY_LABEL"
echo -e ""
echo -e "  ${CYAN}Next steps:${RESET}"
echo -e "  1. Run gen_key.sh to write your auth key to this USB"
echo -e "     ${YELLOW}sudo ./gen_key.sh $TARGET${RESET}"
echo -e ""
echo -e "  2. Set USB as first boot device in BIOS/UEFI"
echo -e ""
echo -e "  3. Boot — GRUB loads to RAM, pull USB after menu appears"
echo -e ""
echo -e "  4. From menu: Install GRUB to disk for permanent install"
echo -e "${BOLD}══════════════════════════════════════════════════${RESET}"
echo
