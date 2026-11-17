#!/usr/bin/env python3
"""
Tests for tools/fetch_ipk.py (issue #3), standard library only, no network.

    python3 tools/test_fetch_ipk.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_ipk  # noqa: E402


def pkg(name, depends=''):
    return {'Package': name, 'Version': '1', 'Depends': depends, 'Filename': name + '.ipk', '_feed': 'http://feed'}


# What the OpenWrt 21.02 feed served in November 2026 (versions left out)
INDEX = {
    'python3-sqlite3': pkg('python3-sqlite3', 'libc, python3-light, libsqlite3-0'),
    'python3-light': pkg('python3-light', 'libc, python3-base, libffi, libbz2-1.0, libuuid1'),
    'python3-base': pkg('python3-base', 'libc, libpython3-3.9'),
    'libpython3-3.9': pkg('libpython3-3.9', 'libc, libpthread, zlib'),
    'libsqlite3-0': pkg('libsqlite3-0', 'libc, libpthread, zlib'),
    'libffi': pkg('libffi', 'libc'),
    'zlib': pkg('zlib', 'libc'),
}

# `opkg list-installed` on firmware 2.1.3 (excerpt)
INSTALLED_213 = """libpython3-3.9 - 3.9.7-1
libsqlite3-0 - 3330000-1
python3-base - 3.9.7-1
python3-light - 3.9.7-1
libffi - 3.3-1
zlib - 1.2.11-3
"""


class FetchIpkTest(unittest.TestCase):

    def names(self, packages):
        return sorted(p['Package'] for p in packages)

    def test_only_the_missing_package_is_downloaded_on_firmware_213(self):
        with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as fh:
            fh.write(INSTALLED_213)
        installed = fetch_ipk.read_installed(fh.name)
        os.unlink(fh.name)
        download, have, _ = fetch_ipk.plan(INDEX, ['python3-sqlite3'], installed)
        self.assertEqual(self.names(download), ['python3-sqlite3'])
        self.assertIn('python3-light', have)
        self.assertIn('libsqlite3-0', have)

    def test_without_the_installed_list_everything_is_followed(self):
        download, _, _ = fetch_ipk.plan(INDEX, ['python3-sqlite3'], set())
        self.assertIn('python3-light', self.names(download))
        self.assertIn('libsqlite3-0', self.names(download))

    def test_wanted_package_already_installed_downloads_nothing(self):
        download, have, _ = fetch_ipk.plan(INDEX, ['libsqlite3-0'], {'libsqlite3-0'})
        self.assertEqual((download, have), ([], ['libsqlite3-0']))

    def test_package_absent_from_the_feeds_is_reported(self):
        _, _, missing = fetch_ipk.plan(INDEX, ['python3-sqlite3'], {'python3-light', 'libsqlite3-0', 'libc'})
        self.assertEqual(missing, [])  # libc is a base package, never followed
        _, _, missing = fetch_ipk.plan(INDEX, ['does-not-exist'], set())
        self.assertEqual(missing, ['does-not-exist'])


class ChecksTest(unittest.TestCase):
    """Audit 8.2: HTTPS feeds, mandatory and matching SHA-256, plain file names."""

    def pkg(self, data=b'ipk', **kw):
        import hashlib
        p = {'Package': 'python3-sqlite3', 'Filename': 'python3-sqlite3_3.9.16-1_mipsel_24kc.ipk',
             'SHA256sum': hashlib.sha256(data).hexdigest()}
        p.update(kw)
        return p

    def test_good_package(self):
        self.assertEqual(fetch_ipk.check_package(self.pkg(), b'ipk'), 'python3-sqlite3_3.9.16-1_mipsel_24kc.ipk')

    def test_missing_or_wrong_checksum_is_refused(self):
        with self.assertRaises(ValueError):
            fetch_ipk.check_package(self.pkg(SHA256sum=''), b'ipk')
        with self.assertRaises(ValueError):
            fetch_ipk.check_package(self.pkg(), b'something else')

    def test_pinned_checksum(self):
        import hashlib
        good = hashlib.sha256(b'ipk').hexdigest()
        self.assertTrue(fetch_ipk.check_package(self.pkg(), b'ipk', expect=good))
        with self.assertRaises(ValueError):
            fetch_ipk.check_package(self.pkg(), b'ipk', expect='0' * 64)

    def test_file_names_that_could_escape_are_refused(self):
        for name in ('../evil.ipk', 'sub/evil.ipk', '.hidden.ipk', 'evil.sh', '/etc/passwd'):
            with self.assertRaises(ValueError, msg=name):
                fetch_ipk.check_package(self.pkg(Filename=name), b'ipk')

    def test_http_feeds_are_refused(self):
        with tempfile.NamedTemporaryFile('w', suffix='.conf', delete=False) as fh:
            fh.write('src/gz base http://downloads.openwrt.org/releases/packages-21.02/mipsel_24kc/base\n')
        with self.assertRaises(SystemExit):
            fetch_ipk.read_feeds(fh.name)
        with open(fh.name, 'w') as out:
            out.write('src/gz base https://downloads.openwrt.org/releases/packages-21.02/mipsel_24kc/base\n')
        self.assertEqual(len(fetch_ipk.read_feeds(fh.name)), 1)
        os.unlink(fh.name)

if __name__ == '__main__':
    unittest.main(verbosity=1)
