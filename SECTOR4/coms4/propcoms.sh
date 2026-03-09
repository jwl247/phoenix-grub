#!/bin/bash
# Daisy chain propcoms: coms4 -> coms3 -> coms2 -> coms1
# No loops — one-way chain for load balance and healing/clone

BASE="/etc/systemd/system/SECTOR4"

CHAIN=(
    "$BASE/coms4/propcoms.py"
    "$BASE/coms3/propcoms.py"
    "$BASE/coms2/propcoms.py"
    "$BASE/coms1/propcoms.py"
)

echo "Linking propcoms chain..."

for i in "${!CHAIN[@]}"; do
    NEXT=$((i + 1))
    if [ $NEXT -lt ${#CHAIN[@]} ]; then
        SRC="${CHAIN[$NEXT]}"
        LINK="${CHAIN[$i]%propcoms.py}propcoms_next.py"

        # Remove existing symlink if present
        [ -L "$LINK" ] && rm "$LINK"

        ln -s "$SRC" "$LINK"
        echo "  Linked: $LINK -> $SRC"
    fi
done

echo "Done. Chain: coms4 -> coms3 -> coms2 -> coms1"
