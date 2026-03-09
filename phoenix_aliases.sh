#!/usr/bin/env bash
# ============================================================
#  Phoenix-DevOps-oS  —  Aliases
#  Source from .zshrc and .bashrc:
#    source ~/phoenix/phoenix_aliases.sh
# ============================================================

# ── UnitedSys shortcuts ───────────────────────────────────────
alias ul='usys list'                    # list all registered packages
alias ur='usys register'                # register a file
alias ui='usys info'                    # version history for a package
alias uc='usys call'                    # call/run a registered package
alias uw='usys where'                   # find where a package lives
alias us='usys swap'                    # hotswap to new version
alias urb='usys rollback'               # roll back a version
alias uss='usys search'                 # search registry

# ── SECTOR4 — direct calls ────────────────────────────────────
alias pcs='usys call pcs'               # PCS engine
alias freewheel='usys call freewheeling-stage'  # Freewheeling stage
alias cpt='usys call conductor'         # Cpt_conductor

# ── Phoenix directory navigation ─────────────────────────────
alias phoenix='cd ~/phoenix'
alias sec4='cd ~/phoenix/SECTOR4'
alias coms1='cd ~/phoenix/SECTOR4/coms1'
alias coms2='cd ~/phoenix/SECTOR4/coms2'
alias coms3='cd ~/phoenix/SECTOR4/coms3'
alias coms4='cd ~/phoenix/SECTOR4/coms4'
alias pscripts='cd ~/phoenix/scripts'

# ── Clonepool ─────────────────────────────────────────────────
alias clonepool='ls /mnt/clonepool/ 2>/dev/null || echo "clonepool not mounted"'
alias zones='btrfs subvolume list /mnt/clonepool 2>/dev/null'
alias cpool='cd /mnt/clonepool'

# ── Auth / USB key ────────────────────────────────────────────
alias keylog='sudo tail -20 /var/log/phoenix_auth.log'
alias keyok='sudo grep OK /var/log/phoenix_auth.log | tail -10'
alias keyfail='sudo grep FAIL /var/log/phoenix_auth.log | tail -10'

# ── Git — phoenix-grub repo ───────────────────────────────────
alias gpush='git -C ~/phoenix push'
alias gstat='git -C ~/phoenix status'
alias glog='git -C ~/phoenix log --oneline -10'
alias gadd='git -C ~/phoenix add'
alias gcommit='git -C ~/phoenix commit'

# ── System ────────────────────────────────────────────────────
alias syslog='sudo journalctl -xe --no-pager | tail -30'
alias rings='systemctl list-units "coms*.service" "phoenix*.service" 2>/dev/null'
