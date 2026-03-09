#!/usr/bin/env bash
# ============================================================
#  recover_scripts.sh  — Multi-drive script recovery tool
#  Author: JW / Phoenix-DevOps-oS
#  Usage:  sudo ./recover_scripts.sh [OUTPUT_DIR]
#  Default output: ~/RECOVERED_SCRIPTS
# ============================================================

set -euo pipefail

OUTPUT_DIR="${1:-$HOME/RECOVERED_SCRIPTS}"
LOG_FILE="$OUTPUT_DIR/recovery.log"
INDEX_FILE="$OUTPUT_DIR/INDEX.txt"
DUP_DIR="$OUTPUT_DIR/_duplicates"

EXTENSIONS=(
  "sh" "bash" "zsh" "fish"
  "py" "pyw"
  "pl" "pm"
  "rb"
  "js" "mjs" "cjs" "ts"
  "php"
  "lua"
  "tcl" "expect"
  "awk" "sed"
  "ps1" "psm1" "psd1"
  "bat" "cmd"
  "go"
  "r" "R"
  "m"
  # systemd unit files
  "service" "timer" "socket" "target" "mount"
  "automount" "path" "slice" "scope" "conf"
  "env" "environment"
)

# Filesystem types to skip
SKIP_FSTYPES=(
  "proc" "sysfs" "devtmpfs" "devpts" "tmpfs"
  "cgroup" "cgroup2" "pstore" "efivarfs"
  "debugfs" "tracefs" "securityfs" "fusectl"
  "hugetlbfs" "mqueue" "autofs" "overlay"
  "squashfs"
)

# Explicit paths to always skip
SKIP_PATHS=(
  "/proc" "/sys" "/dev" "/run"
  "/snap" "/var/lib/docker" "/var/lib/lxc"
  "/tmp" "/lost+found"
)

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

log()  { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG_FILE" >&2; }
info() { echo -e "${CYAN}[INFO]${RESET} $*" >&2; log "INFO: $*"; }
ok()   { echo -e "${GREEN}[OK]${RESET}   $*" >&2; log "OK: $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET} $*" >&2; log "WARN: $*"; }

flatten_path() {
  # /media/jwl247/breach_coms1/scripts/foo.py
  # → media__jwl247__breach_coms1__scripts__foo.py
  echo "$1" | sed 's|^/||; s|/|__|g'
}

has_script_shebang() {
  head -c 100 "$1" 2>/dev/null | grep -qE '^#!(.*)(sh|bash|zsh|fish|python|perl|ruby|node|lua|php|tclsh|expect)'
}

# ── Auto-discover all physical/real mount points ──────────────
get_mount_points() {
  local mounts=()

  while IFS= read -r line; do
    local mountpoint fstype
    mountpoint=$(echo "$line" | awk '{print $2}')
    fstype=$(echo "$line"     | awk '{print $3}')

    # Skip virtual filesystems
    local skip=false
    for ft in "${SKIP_FSTYPES[@]}"; do
      [[ "$fstype" == "$ft" ]] && { skip=true; break; }
    done
    $skip && continue

    # Skip explicit blacklist
    for sp in "${SKIP_PATHS[@]}"; do
      [[ "$mountpoint" == "$sp" || "$mountpoint" == "$sp/"* ]] && { skip=true; break; }
    done
    $skip && continue

    # Skip our own output dir
    [[ "$OUTPUT_DIR" == "$mountpoint"* || "$mountpoint" == "$OUTPUT_DIR"* ]] && continue

    mounts+=("$mountpoint")
  done < /proc/mounts

  # Sort and deduplicate
  printf '%s\n' "${mounts[@]}" | sort -u
}

# ── Scan one root path ────────────────────────────────────────
scan_path() {
  local scanroot="$1"
  local found=0 copied=0 dupes=0 skipped=0

  info "  Scanning: $scanroot"

  # Build -iname args for find
  local first=true
  local ext_args=()
  for ext in "${EXTENSIONS[@]}"; do
    if $first; then
      ext_args+=( -iname "*.${ext}" )
      first=false
    else
      ext_args+=( -o -iname "*.${ext}" )
    fi
  done

  # Extension-based scan
  while IFS= read -r filepath; do
    [[ -f "$filepath" && -r "$filepath" ]] || { ((skipped++)); continue; }
    ((found++))

    local flat dest
    flat=$(flatten_path "$filepath")
    dest="$OUTPUT_DIR/$flat"

    if [[ -e "$dest" ]]; then
      local src_hash dst_hash
      src_hash=$(md5sum "$filepath" 2>/dev/null | awk '{print $1}')
      dst_hash=$(md5sum "$dest"     2>/dev/null | awk '{print $1}')
      if [[ "$src_hash" == "$dst_hash" ]]; then
        ((dupes++)); continue
      else
        dest="$DUP_DIR/${flat}.CONFLICT_$(date +%s%N)"
        ((dupes++))
      fi
    fi

    if cp -p "$filepath" "$dest" 2>/dev/null; then
      ((copied++))
      echo "$filepath" >> "$INDEX_FILE"
    else
      ((skipped++))
    fi

  done < <(find "$scanroot" \( "${ext_args[@]}" \) -type f 2>/dev/null | sort)

  # Shebang scan — executable files with no known extension
  while IFS= read -r filepath; do
    [[ -f "$filepath" && -x "$filepath" && -r "$filepath" ]] || continue

    local skip=false
    for ext in "${EXTENSIONS[@]}"; do
      [[ "$filepath" == *".$ext" ]] && { skip=true; break; }
    done
    $skip && continue

    has_script_shebang "$filepath" || continue

    ((found++))
    local flat dest
    flat=$(flatten_path "$filepath")
    dest="$OUTPUT_DIR/_shebang__${flat}"
    [[ -e "$dest" ]] && dest="${dest}.$(date +%s%N)"

    if cp -p "$filepath" "$dest" 2>/dev/null; then
      ((copied++))
      echo "$filepath  [shebang]" >> "$INDEX_FILE"
    else
      ((skipped++))
    fi

  done < <(find "$scanroot" -type f -executable 2>/dev/null | sort)

  echo "$found $copied $dupes $skipped"
}

generate_report() {
  local total="$1"
  local report="$OUTPUT_DIR/REPORT.md"

  {
    echo "# Script Recovery Report"
    echo "Generated: $(date)"
    echo "Host: $(hostname)"
    echo "Total scripts recovered: $total"
    echo
    echo "## By Type"
    echo '```'
    for ext in "${EXTENSIONS[@]}"; do
      local count
      count=$(find "$OUTPUT_DIR" -maxdepth 1 -iname "*.${ext}" 2>/dev/null | wc -l)
      [[ $count -gt 0 ]] && printf "  %-10s %d\n" ".$ext" "$count"
    done
    local sc
    sc=$(find "$OUTPUT_DIR" -maxdepth 1 -name "_shebang__*" 2>/dev/null | wc -l)
    [[ $sc -gt 0 ]] && printf "  %-10s %d\n" "[shebang]" "$sc"
    echo '```'
    echo
    echo "## Drives / Mount Points Scanned"
    echo '```'
    cat "$OUTPUT_DIR/.scanned_mounts" 2>/dev/null || echo "(none recorded)"
    echo '```'
    echo
    echo "## Full Source Index"
    echo '```'
    cat "$INDEX_FILE" 2>/dev/null || echo "(none)"
    echo '```'
  } > "$report"

  ok "Report written: $report"
}

# ── Main ─────────────────────────────────────────────────────
main() {
  echo -e "${BOLD}╔══════════════════════════════════════════╗${RESET}"
  echo -e "${BOLD}║   PHOENIX MULTI-DRIVE SCRIPT RECOVERY   ║${RESET}"
  echo -e "${BOLD}╚══════════════════════════════════════════╝${RESET}"
  echo

  if [[ $EUID -ne 0 ]]; then
    warn "Not running as root — drives in /media and protected paths may be missed."
    warn "Re-run with: sudo $0 $*"
    echo
  fi

  mkdir -p "$OUTPUT_DIR" "$DUP_DIR"
  > "$LOG_FILE"
  > "$INDEX_FILE"
  > "$OUTPUT_DIR/.scanned_mounts"

  info "Output dir : $OUTPUT_DIR"
  info "Scan start : $(date)"
  echo

  # ── Discover all drives ───────────────────────────────────────
  info "Detecting mount points via /proc/mounts ..."
  mapfile -t MOUNT_POINTS < <(get_mount_points)

  if [[ ${#MOUNT_POINTS[@]} -eq 0 ]]; then
    warn "No mount points detected. Falling back to /."
    MOUNT_POINTS=("/")
  fi

  # Explicitly add /media and /mnt subdirs — catches breach_coms*, clonepool, etc.
  # that may be mounted but not yet reflected in /proc/mounts at scan time
  for extra_root in /media /mnt; do
    [[ -d "$extra_root" ]] || continue
    while IFS= read -r subdir; do
      [[ -d "$subdir" ]] || continue
      local already=false
      for existing_mp in "${MOUNT_POINTS[@]}"; do
        [[ "$existing_mp" == "$subdir" ]] && { already=true; break; }
      done
      $already || MOUNT_POINTS+=("$subdir")
    done < <(find "$extra_root" -mindepth 1 -maxdepth 2 -type d 2>/dev/null)
  done

  # ── High-value system script dirs (RHEL/SECTOR4 targets) ─────
  SYSTEM_DIRS=(
    /etc/systemd
    /etc/systemd/system
    /etc/sysconfig
    /etc/profile.d
    /etc/init.d
    /etc/cron.d
    /etc/cron.daily
    /etc/cron.hourly
    /etc/cron.weekly
    /etc/cron.monthly
    /usr/local/bin
    /usr/local/sbin
    /usr/local/lib/systemd
    /root
  )

  for sdir in "${SYSTEM_DIRS[@]}"; do
    [[ -d "$sdir" ]] || continue
    local already=false
    for existing_mp in "${MOUNT_POINTS[@]}"; do
      [[ "$existing_mp" == "$sdir" ]] && { already=true; break; }
    done
    if ! $already; then
      MOUNT_POINTS+=("$sdir")
      info "  Added system dir: $sdir"
    fi
  done

  echo
  echo -e "${BOLD}  Drives / partitions to scan (${#MOUNT_POINTS[@]} found):${RESET}"
  for mp in "${MOUNT_POINTS[@]}"; do
    local device fstype size
    device=$(awk -v m="$mp" '$2==m{print $1;exit}' /proc/mounts 2>/dev/null || echo "unknown")
    fstype=$(awk -v m="$mp" '$2==m{print $3;exit}' /proc/mounts 2>/dev/null || echo "unknown")
    size=$(df -h "$mp" 2>/dev/null | awk 'NR==2{print $2}' || echo "?")
    echo -e "    ${GREEN}✓${RESET}  ${BOLD}$mp${RESET}  ${CYAN}[$device | $fstype | $size]${RESET}"
    echo "$mp  [$device | $fstype | $size]" >> "$OUTPUT_DIR/.scanned_mounts"
  done
  echo

  # ── Scan each mount point ─────────────────────────────────────
  local total_found=0 total_copied=0 total_dupes=0 total_skipped=0

  for mp in "${MOUNT_POINTS[@]}"; do
    local result
    result=$(scan_path "$mp")
    local f c d s
    f=$(awk '{print $1}' <<< "$result")
    c=$(awk '{print $2}' <<< "$result")
    d=$(awk '{print $3}' <<< "$result")
    s=$(awk '{print $4}' <<< "$result")

    ((total_found   += f))
    ((total_copied  += c))
    ((total_dupes   += d))
    ((total_skipped += s))

    echo -e "    → found=${GREEN}${f}${RESET}  copied=${GREEN}${c}${RESET}  dupes=${YELLOW}${d}${RESET}  skipped=${RED}${s}${RESET}"
    echo
  done

  # ── Summary ───────────────────────────────────────────────────
  echo -e "${BOLD}══════════════════ RECOVERY SUMMARY ══════════════════${RESET}"
  echo -e "  ${CYAN}Drives scanned       :${RESET} ${#MOUNT_POINTS[@]}"
  echo -e "  ${GREEN}Scripts found        :${RESET} $total_found"
  echo -e "  ${GREEN}Successfully copied  :${RESET} $total_copied"
  echo -e "  ${YELLOW}Duplicates/conflicts :${RESET} $total_dupes"
  echo -e "  ${RED}Skipped (no access)  :${RESET} $total_skipped"
  echo -e "  ${CYAN}Output directory     :${RESET} $OUTPUT_DIR"
  echo -e "  ${CYAN}Index                :${RESET} $INDEX_FILE"
  echo -e "${BOLD}═══════════════════════════════════════════════════════${RESET}"
  echo

  log "DONE — drives=${#MOUNT_POINTS[@]} found=$total_found copied=$total_copied dupes=$total_dupes skipped=$total_skipped"

  generate_report "$total_copied"
}

main "$@"
