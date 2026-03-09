#!/usr/bin/env bash
# Non-interactive Phoenix USB builder — target hardcoded to /dev/sdg
set -euo pipefail

TARGET="/dev/sdg"
PART="${TARGET}1"
MNT="/tmp/phoenix_usb"
GRUB_CFG="/home/jwl247/phoenix/grub/grub.cfg"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; RESET='\033[0m'
info() { echo -e "${CYAN}[*]${RESET} $*"; }
ok()   { echo -e "${GREEN}[+]${RESET} $*"; }
die()  { echo -e "${RED}[!]${RESET} $*"; exit 1; }

[[ $EUID -ne 0 ]] && die "Run as root: sudo bash build_now.sh"
[[ -b "$TARGET" ]] || die "Device $TARGET not found"

info "Partitioning $TARGET ..."
parted -s "$TARGET" mklabel gpt
parted -s "$TARGET" mkpart primary fat32 1MiB 100%
parted -s "$TARGET" set 1 esp on
parted -s "$TARGET" set 1 boot on
sleep 2
partprobe "$TARGET" 2>/dev/null || true
sleep 2
[[ -b "$PART" ]] || die "Partition $PART not found after partitioning"
ok "Partitioned"

info "Formatting $PART as FAT32 ..."
mkfs.vfat -F32 -n PHOENIX-KEY "$PART"
ok "Formatted"

info "Mounting $PART ..."
mkdir -p "$MNT/boot/grub" "$MNT/EFI/BOOT"
mount "$PART" "$MNT"
ok "Mounted"

info "Installing GRUB (BIOS) ..."
grub-install --target=i386-pc --boot-directory="$MNT/boot" --recheck "$TARGET" 2>&1 || \
    ok "BIOS install skipped (may be EFI-only system)"

info "Building EFI image ..."
if [[ -d /usr/lib/grub/x86_64-efi ]]; then
    grub-mkimage \
        --directory /usr/lib/grub/x86_64-efi \
        --prefix /boot/grub \
        --output "$MNT/EFI/BOOT/BOOTX64.EFI" \
        --format x86_64-efi \
        all_video fat ext2 part_gpt part_msdos normal configfile \
        linux memdisk tar search search_label echo test true reboot halt
    ok "EFI image built"
else
    ok "EFI modules not found — BIOS only"
fi

info "Copying grub.cfg ..."
cp "$GRUB_CFG" "$MNT/boot/grub/grub.cfg"
ok "grub.cfg copied"

info "Cleaning up ..."
umount "$MNT"
rm -rf "$MNT"

echo ""
ok "Phoenix USB built on $TARGET"
echo -e "${CYAN}Next: sudo bash /home/jwl247/phoenix/scripts/gen_key.sh $TARGET${RESET}"
