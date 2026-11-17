#!/bin/bash
# Build the Sentinel module.
#   ./build.sh            compile into dist/Sentinel
#   ./build.sh package    + Sentinel-<version>.tar.gz
#   ./build.sh release    + release/ : the module, python3-sqlite3, the install scripts, SHA256SUMS
#   ./build.sh copy       + copy dist/Sentinel to a Pineapple over SCP
set -euo pipefail
cd "$(dirname "$0")"

# The module name is fixed: the repository folder can have any name
MODULENAME=Sentinel

prepare_workspace() {
    if [ -d node_modules ]; then
        return
    fi
    command -v npm >/dev/null || { echo "[!] npm is not installed"; exit 1; }
    echo "[*] Preparing the Angular workspace (npm ci)"
    npm ci --no-audit --no-fund >/dev/null
}

build_module() {
    # The Angular 9 toolchain needs the legacy OpenSSL provider on Node.js 17 and newer
    if [ "$(node -p 'process.versions.node.split(".")[0]')" -ge 17 ]; then
        export NODE_OPTIONS="${NODE_OPTIONS:-} --openssl-legacy-provider"
    fi
    if ! npx --no-install ng build --prod >build.log 2>&1; then
        echo "[!] Angular build failed, see build.log"
        exit 1
    fi
    rm -f build.log
    echo "[*] Angular build succeeded"

    local out="dist/$MODULENAME"
    cp projects/$MODULENAME/src/module.svg projects/$MODULENAME/src/module.json "$out/bundles/"
    cp projects/$MODULENAME/src/module.py "$out/bundles/"
    cp -r projects/$MODULENAME/src/assets "$out/bundles/"
    # Only what the Pineapple needs: no source maps, no minified duplicate, no Python caches
    find "$out/bundles" -name '__pycache__' -prune -exec rm -rf {} +
    rm -f "$out"/bundles/*.map "$out"/bundles/*.min*
    rm -rf bundletmp
    mv "$out/bundles" bundletmp
    rm -rf "${out:?}"/*
    mv bundletmp/* "$out/"
    rm -rf bundletmp
}

package() {
    local version
    version=$(python3 -c "import json; print(json.load(open('dist/$MODULENAME/module.json'))['version'])")
    rm -f "$MODULENAME-$version.tar.gz"
    echo "[*] Packaging $MODULENAME (version $version)"
    # Files owned by root in the archive, whoever builds it (audit 8.5)
    if tar --version 2>/dev/null | grep -q 'GNU tar'; then
        tar --owner=0 --group=0 --numeric-owner -C dist -czf "$MODULENAME-$version.tar.gz" "$MODULENAME"
    else
        tar --uid 0 --gid 0 -C dist -czf "$MODULENAME-$version.tar.gz" "$MODULENAME"
    fi
}

release() {
    package
    local version ipk expected
    version=$(python3 -c "import json; print(json.load(open('dist/$MODULENAME/module.json'))['version'])")
    read -r expected ipk < vendor/python3-sqlite3.sha256
    rm -rf release && mkdir release
    cp "$MODULENAME-$version.tar.gz" release/
    # The exact python3-sqlite3 validated on the device: a cached copy if it is the right
    # file, otherwise from the OpenWrt feed (HTTPS, checksum pinned)
    if [ -f "vendor/$ipk" ] && [ "$(sha256sum "vendor/$ipk" | cut -d' ' -f1)" = "$expected" ]; then
        cp "vendor/$ipk" release/
    else
        python3 tools/fetch_ipk.py vendor/distfeeds.conf python3-sqlite3 --no-deps \
            --expect-sha256 "$expected" --out release >/dev/null
        cp "release/$ipk" "vendor/$ipk"
    fi
    [ "$(sha256sum "release/$ipk" | cut -d' ' -f1)" = "$expected" ] || { echo "[!] wrong $ipk"; exit 1; }
    for script in install.sh uninstall.sh install-from-pc.sh; do
        sed "s/@VERSION@/$version/g" "installer/$script" > "release/$script"
        chmod 755 "release/$script"
    done
    (cd release && sha256sum "$MODULENAME-$version.tar.gz" "$ipk" install.sh uninstall.sh install-from-pc.sh > SHA256SUMS)
    echo "[*] release/ is ready:"
    ls -1 release | sed 's/^/      /'
}

copy_to_device() {
    echo "[*] Copying the module to the WiFi Pineapple over SCP"
    scp -O -r "dist/$MODULENAME" root@172.16.42.1:/pineapple/modules
}

main() {
    prepare_workspace
    build_module
    case "${1:-}" in
        package) package ;;
        release) release ;;
        copy) copy_to_device ;;
        '') ;;
        *) echo "[!] Unknown target: $1"; exit 1 ;;
    esac
    echo "[*] Success!"
}

main "$@"
