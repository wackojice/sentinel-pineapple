#!/usr/bin/env python3
"""
Download an OpenWrt package and its dependencies on a trusted computer, so the
WiFi Pineapple never needs Internet access (no connection sharing, no bridge).

1. On the Pineapple, copy its feed list and the list of installed packages:
       scp -O root@172.16.42.1:/etc/opkg/distfeeds.conf .
       ssh root@172.16.42.1 opkg list-installed > installed.txt
2. On your computer (Python 3 standard library only):
       python3 tools/fetch_ipk.py distfeeds.conf python3-sqlite3 --installed installed.txt --out ipk/
3. Copy and install on the Pineapple:
       scp -O ipk/*.ipk root@172.16.42.1:/tmp/
       ssh root@172.16.42.1 'opkg install /tmp/*.ipk && rm /tmp/*.ipk'

Only what is missing is downloaded. This matters: the feeds of a release keep moving
(OpenWrt 21.02 now serves Python 3.9.16 while firmware 2.1.3 has 3.9.7), so installing
newer copies of packages that are already there would upgrade part of the system and
leave the rest behind. Each download is checked against the SHA-256 of the feed index.
"""

import argparse
import gzip
import hashlib
import os
import re
import sys
import urllib.request

# Always present on the Pineapple firmware: never download them.
BASE = {'libc', 'libgcc', 'libgcc1', 'libpthread', 'librt', 'busybox', 'kernel'}


IPK_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+-]*\.ipk$')


def read_feeds(path):
    """Feed URLs of distfeeds.conf. HTTPS only (audit 8.2): the index is the only proof of
    what a package should contain, so it must not be readable or changeable on the way."""
    feeds = []
    with open(path) as fh:
        for line in fh:
            parts = line.split()
            if len(parts) >= 3 and parts[0] in ('src/gz', 'src'):
                url = parts[2].rstrip('/')
                if not url.startswith('https://'):
                    sys.exit('Refused: feed is not HTTPS: %s' % url)
                feeds.append(url)
    if not feeds:
        sys.exit('No feed found in %s' % path)
    return feeds


def check_package(pkg, data, expect=None):
    """
    The file name to save `data` under, after the checks; raises ValueError otherwise.
    The feed index must give a SHA-256 and it must match (audit 8.2); `expect`, when
    given, pins the exact file (release builds). The name must be a plain .ipk name.
    """
    name = pkg.get('Filename') or ''
    if not IPK_NAME.match(name):  # a plain name: no folder, no "..", nothing to escape --out
        raise ValueError('suspicious file name in the index: %r' % pkg.get('Filename'))
    want = (pkg.get('SHA256sum') or '').lower()
    if not re.match(r'^[0-9a-f]{64}$', want):
        raise ValueError('no SHA-256 in the index for %s: download refused' % pkg.get('Package'))
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        raise ValueError('checksum mismatch for %s: download refused' % pkg.get('Package'))
    if expect and got != expect.lower():
        raise ValueError('%s is not the pinned file (%s): download refused' % (name, expect[:12]))
    return name


def load_index(feed):
    """Packages index of one feed: {name: {field: value, '_feed': url}}."""
    for name in ('Packages.gz', 'Packages'):
        try:
            data = urllib.request.urlopen('%s/%s' % (feed, name), timeout=30).read()
        except Exception:
            continue
        if name.endswith('.gz'):
            data = gzip.decompress(data)
        packages, current = {}, {}
        for line in data.decode('utf-8', 'replace').splitlines() + ['']:
            if not line.strip():
                if current.get('Package'):
                    current['_feed'] = feed
                    packages[current['Package']] = current
                current = {}
            elif ':' in line and not line.startswith(' '):
                k, v = line.split(':', 1)
                current[k.strip()] = v.strip()
        return packages
    print('  (feed unreachable: %s)' % feed, file=sys.stderr)
    return {}


def deps_of(pkg):
    out = []
    for d in (pkg.get('Depends') or '').split(','):
        d = d.strip().split(' ')[0].split('(')[0].strip()
        if d and d not in BASE:
            out.append(d)
    return out


def read_installed(path):
    """Names from the output of `opkg list-installed` ("name - version" per line)."""
    names = set()
    with open(path) as fh:
        for line in fh:
            name = line.split(' - ')[0].strip()
            if name:
                names.add(name)
    return names


def plan(index, wanted, installed):
    """
    Packages to download: the wanted ones and their dependencies, minus what is
    installed already (whose own dependencies are then not followed either).
    Returns (to_download, skipped_installed, not_in_feeds).
    """
    todo, seen = list(wanted), set()
    download, have, missing = [], [], []
    while todo:
        name = todo.pop(0)
        if name in seen:
            continue
        seen.add(name)
        if name in installed:
            have.append(name)
            continue
        pkg = index.get(name)
        if not pkg:
            missing.append(name)
            continue
        download.append(pkg)
        todo.extend(deps_of(pkg))
    return download, have, missing


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('distfeeds', help="copy of the Pineapple's /etc/opkg/distfeeds.conf")
    ap.add_argument('packages', nargs='+', help='packages to fetch, e.g. python3-sqlite3')
    ap.add_argument('--out', default='ipk', help='output folder (default: ipk/)')
    ap.add_argument('--installed', help='output of `opkg list-installed` on the Pineapple (strongly recommended)')
    ap.add_argument('--expect-sha256', help='refuse the requested package unless it is exactly this file')
    ap.add_argument('--no-deps', action='store_true', help='download only the requested packages')
    args = ap.parse_args()

    installed = read_installed(args.installed) if args.installed else set()
    if not args.installed and not args.no_deps:
        print('WARNING: without --installed, packages the Pineapple already has are downloaded too.\n'
              '         Installing them would replace the firmware\'s versions. Install only what is missing.',
              file=sys.stderr)

    index = {}
    for feed in read_feeds(args.distfeeds):
        for name, pkg in load_index(feed).items():
            index.setdefault(name, pkg)

    if args.no_deps:
        download = [index[n] for n in args.packages if n in index]
        have, missing = [], [n for n in args.packages if n not in index]
    else:
        download, have, missing = plan(index, args.packages, installed)
    for name in have:
        print('  already installed, skipped: %s' % name)
    for name in missing:
        # Virtual or base package (e.g. provided by the firmware): opkg will resolve it
        print('  skipped (not in feeds, probably built into the firmware): %s' % name)
    if not download:
        print('Nothing to download: everything is installed already.')
        return
    os.makedirs(args.out, exist_ok=True)
    for pkg in download:
        url = '%s/%s' % (pkg['_feed'], pkg['Filename'])
        data = urllib.request.urlopen(url, timeout=60).read()
        try:
            name = check_package(pkg, data, args.expect_sha256 if pkg['Package'] in args.packages else None)
        except ValueError as e:
            sys.exit(str(e))
        dest = os.path.join(args.out, name)
        with open(dest, 'wb') as fh:
            fh.write(data)
        print('  %s %s -> %s' % (pkg['Package'], pkg.get('Version', ''), dest))
    print('Done. Copy %s/*.ipk to the Pineapple and run opkg install.' % args.out)


if __name__ == '__main__':
    main()
