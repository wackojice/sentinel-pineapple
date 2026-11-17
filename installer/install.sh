#!/bin/sh
# Sentinel @VERSION@ - installer, run on the WiFi Pineapple Mark VII as root.
#
#   sh install.sh            install or upgrade the module, and python3-sqlite3 if missing
#   sh install.sh --reboot   the same, then reboot the Pineapple (needed after an upgrade)
#
# Everything it uses must sit next to it and match SHA256SUMS. It downloads nothing.
# Settings, data and your marked networks (/root/.Sentinel) are never touched.
set -eu

VERSION="@VERSION@"
IPK="python3-sqlite3_3.9.16-1_mipsel_24kc.ipk"
ARCHIVE="Sentinel-$VERSION.tar.gz"

# Overridable for the tests only (tools/test_install.py); empty on the device
ROOT="${SENTINEL_ROOT:-}"
OPKG="${SENTINEL_OPKG:-opkg}"
PYTHON="${SENTINEL_PYTHON:-python3}"
PROC="${SENTINEL_PROC:-/proc}"
REBOOT_CMD="${SENTINEL_REBOOT:-reboot}"
MODULES="$ROOT/pineapple/modules"
DATA="$ROOT/root/.Sentinel"
RUN="$ROOT/tmp"

say() { echo "[*] $*"; }
warn() { echo "[!] $*"; }
die() { echo "[x] $*" >&2; exit 1; }

REBOOT=0
for arg in "$@"; do
    case "$arg" in
        --reboot) REBOOT=1 ;;
        *) die "unknown option: $arg (only --reboot)" ;;
    esac
done

cd "$(dirname "$0")"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# The SHA-256 of a file must be the one written in SHA256SUMS
check_sum() {
    expected=$(awk -v f="$1" '$2 == f || $2 == "*" f { print $1 }' SHA256SUMS)
    [ -n "$expected" ] || die "no checksum for $1 in SHA256SUMS"
    actual=$(sha256sum "$1" | cut -d' ' -f1)
    [ "$expected" = "$actual" ] || die "checksum mismatch for $1: refusing to install it"
}

# Stop a running engine, only if the PID really is Sentinel's engine
stop_engine() {
    pidfile="$RUN/sentinel-engine.pid"
    [ -f "$pidfile" ] || return 0
    pid=$(cat "$pidfile" 2>/dev/null || true)
    case "$pid" in ''|*[!0-9]*) return 0 ;; esac
    if ! tr '\0' ' ' < "$PROC/$pid/cmdline" 2>/dev/null | grep -q '/Sentinel/assets/engine/engine.py'; then
        warn "PID file does not point to Sentinel's engine: no signal sent"
        return 0
    fi
    say "Stopping the running engine"
    kill -TERM "$pid" 2>/dev/null || true
    n=0
    while kill -0 "$pid" 2>/dev/null && [ "$n" -lt 5 ]; do sleep 1; n=$((n + 1)); done
    kill -KILL "$pid" 2>/dev/null || true
    n=0
    while kill -0 "$pid" 2>/dev/null && [ "$n" -lt 5 ]; do sleep 1; n=$((n + 1)); done
}

python_packages() {
    "$OPKG" list-installed 2>/dev/null | grep -E '^(python3|libpython3|libsqlite3)' || true
}

# 1. Root, on a Pineapple
if [ -z "$ROOT" ] && [ "$(id -u)" != 0 ]; then
    die "run it as root on the Pineapple"
fi
[ -d "$MODULES" ] || die "$MODULES does not exist: is this a WiFi Pineapple Mark VII?"

# 2. Files and checksums
[ -f SHA256SUMS ] || die "SHA256SUMS is missing next to install.sh"
[ -f "$ARCHIVE" ] || die "$ARCHIVE is missing next to install.sh"
check_sum "$ARCHIVE"

# 3. The archive may only contain Sentinel/..., plain files and folders, no ".."
tar -tvzf "$ARCHIVE" > "$TMP/list" 2>/dev/null || die "$ARCHIVE cannot be read"
bad=$(awk '{ name = $NF; type = substr($1, 1, 1)
             if (type != "-" && type != "d") { print name; exit }
             if (name !~ /^Sentinel\// && name != "Sentinel/" && name != "Sentinel") { print name; exit }
             if (name ~ /(^|\/)\.\.(\/|$)/) { print name; exit } }' "$TMP/list")
[ -z "$bad" ] || die "unexpected entry in $ARCHIVE: $bad"

# 4. Replace the module (settings and data live elsewhere)
UPGRADE=0
[ -d "$MODULES/Sentinel" ] && UPGRADE=1
stop_engine
rm -rf "$MODULES/Sentinel"
tar -xzf "$ARCHIVE" -C "$MODULES"
[ -n "$ROOT" ] || chown -R 0:0 "$MODULES/Sentinel"
if [ -f uninstall.sh ]; then
    cp uninstall.sh "$MODULES/Sentinel/uninstall.sh"
    chmod 700 "$MODULES/Sentinel/uninstall.sh"
fi
say "Module installed in $MODULES/Sentinel"

# 5. python3-sqlite3, only this package, only if missing
if "$PYTHON" -c 'import sqlite3' 2>/dev/null; then
    say "python3-sqlite3 is already installed"
elif ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 9))' 2>/dev/null; then
    warn "$IPK is built for Python 3.9, and this Pineapple has another version: not installed."
    warn "Install python3-sqlite3 from the module (Settings), or with opkg."
elif ! "$OPKG" print-architecture 2>/dev/null | grep -q 'mipsel_24kc'; then
    warn "$IPK is built for mipsel_24kc, and this device is not: not installed."
elif [ ! -f "$IPK" ]; then
    warn "$IPK is missing next to install.sh: python3-sqlite3 not installed."
else
    check_sum "$IPK"
    python_packages > "$TMP/before"
    say "Installing $IPK"
    "$OPKG" install "./$IPK" || die "opkg could not install $IPK"
    python_packages > "$TMP/after"
    "$PYTHON" -c 'import sqlite3' 2>/dev/null || die "python3-sqlite3 is still not usable"
    changed=$(grep -vxF -f "$TMP/before" "$TMP/after" | grep -v '^python3-sqlite3 ' || true)
    if [ -n "$changed" ]; then
        warn "Other Python packages were changed by the install:"
        echo "$changed"
    fi
fi

# 6. Data folder, root only
mkdir -p "$DATA"
chmod 700 "$DATA"

# 7. What next
say "Sentinel $VERSION is installed."
if [ "$REBOOT" = 1 ]; then
    say "Rebooting the Pineapple. Then reload the web interface with Ctrl+Shift+R."
    $REBOOT_CMD
elif [ "$UPGRADE" = 1 ]; then
    say "Upgrade: reboot the Pineapple now (the old module backend stays in memory until then),"
    say "then reload the web interface with Ctrl+Shift+R. Or run: sh install.sh --reboot"
else
    say "Reload the Pineapple web interface and open Sentinel."
fi
