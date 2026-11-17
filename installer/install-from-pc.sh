#!/bin/sh
# Sentinel @VERSION@ - install from a Linux or macOS computer connected to the Pineapple.
#
#   sh install-from-pc.sh [--reboot] [address]      (address: 172.16.42.1 by default)
#
# Checks the files, copies them to a fresh folder on the Pineapple, runs install.sh there
# and removes the folder. You type the Pineapple's root password (twice).
set -eu

VERSION="@VERSION@"
FILES="Sentinel-$VERSION.tar.gz python3-sqlite3_3.9.16-1_mipsel_24kc.ipk install.sh uninstall.sh SHA256SUMS"
HOST=172.16.42.1
OPTS=""
for arg in "$@"; do
    case "$arg" in
        --reboot) OPTS="--reboot" ;;
        -*) echo "unknown option: $arg" >&2; exit 1 ;;
        *) HOST="$arg" ;;
    esac
done

cd "$(dirname "$0")"

sha() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
    else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

for f in $FILES; do
    [ -f "$f" ] || { echo "missing file: $f" >&2; exit 1; }
    [ "$f" = SHA256SUMS ] && continue
    expected=$(awk -v f="$f" '$2 == f || $2 == "*" f { print $1 }' SHA256SUMS)
    [ "$expected" = "$(sha "$f")" ] || { echo "checksum mismatch for $f: stopping" >&2; exit 1; }
done
echo "[*] Files checked"

# A dedicated folder, so no other .ipk lying in /tmp can be installed by mistake
ssh "root@$HOST" 'rm -rf /tmp/sentinel-install && mkdir /tmp/sentinel-install'
# OpenSSH 9 needs -O for the Pineapple's SSH server; older versions do not know it
if scp -O 2>&1 | grep -qi 'illegal option\|unknown option'; then SCP="scp"; else SCP="scp -O"; fi
# shellcheck disable=SC2086
$SCP $FILES "root@$HOST:/tmp/sentinel-install/"
ssh "root@$HOST" "cd /tmp/sentinel-install && sh install.sh $OPTS; rc=\$?; rm -rf /tmp/sentinel-install; exit \$rc"
