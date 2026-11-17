#!/bin/sh
# Sentinel @VERSION@ - uninstall, run on the WiFi Pineapple Mark VII as root.
#
#   sh uninstall.sh                   remove the module; keep its data and python3-sqlite3
#   sh uninstall.sh --purge           also delete /root/.Sentinel (data, settings, your networks)
#   sh uninstall.sh --remove-sqlite   also remove the python3-sqlite3 package
set -eu

ROOT="${SENTINEL_ROOT:-}"
OPKG="${SENTINEL_OPKG:-opkg}"
IW="${SENTINEL_IW:-iw}"
IP="${SENTINEL_IP:-ip}"
PROC="${SENTINEL_PROC:-/proc}"
MODULES="$ROOT/pineapple/modules"
DATA="$ROOT/root/.Sentinel"
RUN="$ROOT/tmp"
STATE="$RUN/sentinel-radios.json"

say() { echo "[*] $*"; }
warn() { echo "[!] $*"; }
die() { echo "[x] $*" >&2; exit 1; }

PURGE=0
REMOVE_SQLITE=0
for arg in "$@"; do
    case "$arg" in
        --purge) PURGE=1 ;;
        --remove-sqlite) REMOVE_SQLITE=1 ;;
        *) die "unknown option: $arg (--purge, --remove-sqlite)" ;;
    esac
done

if [ -z "$ROOT" ] && [ "$(id -u)" != 0 ]; then
    die "run it as root on the Pineapple"
fi

# Interface names written in the radio state file: plain names only
names() {
    sed -n "s/.*\"$1\": *\[\([^]]*\)\].*/\1/p" "$STATE" | tr -d '" ' | tr ',' '\n' |
        grep -E '^[A-Za-z0-9_.-]{1,15}$' || true
}

# 1. Stop the engine, only if the PID really is Sentinel's engine
pidfile="$RUN/sentinel-engine.pid"
if [ -f "$pidfile" ]; then
    pid=$(cat "$pidfile" 2>/dev/null || true)
    case "$pid" in
        ''|*[!0-9]*) ;;
        *)
            if tr '\0' ' ' < "$PROC/$pid/cmdline" 2>/dev/null | grep -q '/Sentinel/assets/engine/engine.py'; then
                say "Stopping the engine"
                kill -TERM "$pid" 2>/dev/null || true
                n=0
                while kill -0 "$pid" 2>/dev/null && [ "$n" -lt 5 ]; do sleep 1; n=$((n + 1)); done
                kill -KILL "$pid" 2>/dev/null || true
                n=0
                while kill -0 "$pid" 2>/dev/null && [ "$n" -lt 5 ]; do sleep 1; n=$((n + 1)); done
            else
                warn "PID file does not point to Sentinel's engine: no signal sent"
            fi
            ;;
    esac
fi

# 2. Undo what Sentinel changed on the radios (never wlan1mon: it belongs to the Pineapple)
if [ -f "$STATE" ]; then
    for name in $(names created); do
        [ "$name" = wlan1mon ] && continue
        say "Removing monitor interface $name"
        "$IW" dev "$name" del 2>/dev/null || warn "could not remove $name"
    done
    for name in $(names downed); do
        say "Bringing $name back up"
        "$IP" link set "$name" up 2>/dev/null || warn "could not bring $name up"
    done
else
    warn "No record of the radio changes. If needed, run by hand:"
    warn "  iw dev <monitor interface> del ; ip link set <its parent> up   (e.g. wlan3mon and wlan3)"
fi

# 3. The module and its temporary files
rm -rf "$MODULES/Sentinel"
rm -f "$RUN/sentinel-engine.pid" "$RUN/sentinel-engine.log" "$STATE"
say "Module removed"

# 4. Data
if [ "$PURGE" = 1 ]; then
    rm -rf "$DATA"
    say "Data deleted ($DATA)"
else
    say "Kept $DATA (network names and addresses seen nearby, settings, your networks)."
    say "Run again with --purge to delete it."
fi

# 5. The dependency
if [ "$REMOVE_SQLITE" = 1 ]; then
    "$OPKG" remove python3-sqlite3 || warn "opkg could not remove python3-sqlite3"
    say "python3-sqlite3 removed"
else
    say "Kept python3-sqlite3. Run again with --remove-sqlite to remove it."
fi
