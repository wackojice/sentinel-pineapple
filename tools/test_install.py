#!/usr/bin/env python3
"""
Tests for installer/install.sh, uninstall.sh and install-from-pc.sh. Standard library
only, no Pineapple: each test builds a fake device root in a temporary folder and
runs the scripts with BusyBox (like on the Pineapple) when it is installed, and with
fake `opkg`, `python3`, `iw` and `ip` that record their arguments.

    python3 tools/test_install.py
"""

import hashlib
import io
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
INSTALLER = os.path.join(HERE, '..', 'installer')
VERSION = '9.9.9'
IPK = 'python3-sqlite3_3.9.16-1_mipsel_24kc.ipk'
BUSYBOX = shutil.which('busybox')
APPLETS = ['sh', 'awk', 'sed', 'grep', 'tr', 'cut', 'cat', 'rm', 'mkdir', 'chmod', 'cp', 'mv', 'tar',
           'sha256sum', 'mktemp', 'sleep', 'head', 'id', 'touch', 'gzip', 'ls']

FAKE_PYTHON = r'''#!/bin/sh
case "$*" in
    *"import sqlite3"*) [ -f "$FAKE/sqlite_ok" ] && exit 0 || exit 1 ;;
    *version_info*) [ "$(cat "$FAKE/pyver")" = "3.9" ] && exit 0 || exit 1 ;;
esac
exit 0
'''
FAKE_OPKG = r'''#!/bin/sh
echo "$*" >> "$FAKE/opkg.log"
case "$1" in
    print-architecture) cat "$FAKE/arch" ;;
    list-installed) cat "$FAKE/installed" ;;
    install)
        touch "$FAKE/sqlite_ok"
        echo "python3-sqlite3 - 3.9.16-1" >> "$FAKE/installed"
        if [ -f "$FAKE/upgrade_light" ]; then
            sed -i 's/^python3-light - .*/python3-light - 3.9.16-1/' "$FAKE/installed"
        fi ;;
esac
exit 0
'''
FAKE_LOGGER = '#!/bin/sh\necho "$0 $*" >> "$FAKE/commands.log"\nexit 0\n'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def archive(entries):
    """A .tar.gz in memory: entries = [(name, data or None for a folder, or ('link', target))]."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        for name, data in entries:
            info = tarfile.TarInfo(name)
            if data is None:
                info.type, info.mode = tarfile.DIRTYPE, 0o755
                tar.addfile(info)
            elif isinstance(data, tuple):
                info.type, info.linkname = tarfile.SYMTYPE, data[1]
                tar.addfile(info)
            else:
                info.size, info.mode = len(data), 0o644
                tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


GOOD_ARCHIVE = [('Sentinel', None), ('Sentinel/module.json', b'{"version": "9.9.9"}'),
                ('Sentinel/module.py', b'# backend'), ('Sentinel/assets', None),
                ('Sentinel/assets/engine', None), ('Sentinel/assets/engine/engine.py', b'# engine')]


class InstallTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, 'root')
        self.fake = os.path.join(self.tmp, 'fake')
        self.proc = os.path.join(self.tmp, 'proc')
        self.release = os.path.join(self.tmp, 'release')
        self.bin = os.path.join(self.tmp, 'bin')
        for d in (self.root + '/pineapple/modules', self.root + '/tmp', self.fake, self.proc,
                  self.release, self.bin):
            os.makedirs(d)
        self.write(self.fake + '/pyver', '3.9')
        self.write(self.fake + '/arch', 'arch all 1\narch noarch 1\narch mipsel_24kc 10\n')
        self.write(self.fake + '/installed', 'python3-base - 3.9.7-1\npython3-light - 3.9.7-1\n'
                                             'libsqlite3-0 - 3330000-1\n')
        # Tools: BusyBox applets when available (as on the Pineapple), else the system's
        for applet in APPLETS:
            target = BUSYBOX if BUSYBOX else shutil.which(applet)
            if target:
                link = os.path.join(self.bin, applet)
                if BUSYBOX:
                    with open(link, 'w') as fh:
                        fh.write('#!%s sh\nexec %s %s "$@"\n' % (BUSYBOX, BUSYBOX, applet))
                    os.chmod(link, 0o755)
                else:
                    os.symlink(target, link)
        for name, body in (('opkg', FAKE_OPKG), ('python3', FAKE_PYTHON), ('iw', FAKE_LOGGER),
                           ('ip', FAKE_LOGGER), ('reboot', FAKE_LOGGER)):
            self.write(os.path.join(self.bin, name), body, mode=0o755)
        self.release_files()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, path, text, mode=None):
        with open(path, 'w') as fh:
            fh.write(text)
        if mode:
            os.chmod(path, mode)

    def release_files(self, entries=GOOD_ARCHIVE, ipk=b'fake ipk', sums=None):
        data = archive(entries)
        with open(os.path.join(self.release, 'Sentinel-%s.tar.gz' % VERSION), 'wb') as fh:
            fh.write(data)
        with open(os.path.join(self.release, IPK), 'wb') as fh:
            fh.write(ipk)
        for script in ('install.sh', 'uninstall.sh', 'install-from-pc.sh'):
            with open(os.path.join(INSTALLER, script)) as fh:
                body = fh.read().replace('@VERSION@', VERSION)
            self.write(os.path.join(self.release, script), body, mode=0o755)
        sums = sums or {}
        lines = ['%s  %s' % (sums.get('archive', sha(data)), 'Sentinel-%s.tar.gz' % VERSION),
                 '%s  %s' % (sums.get('ipk', sha(ipk)), IPK)]
        self.write(os.path.join(self.release, 'SHA256SUMS'), '\n'.join(lines) + '\n')

    def run_script(self, script, *args):
        env = {'PATH': self.bin, 'FAKE': self.fake, 'SENTINEL_ROOT': self.root,
               'SENTINEL_OPKG': os.path.join(self.bin, 'opkg'),
               'SENTINEL_PYTHON': os.path.join(self.bin, 'python3'),
               'SENTINEL_IW': os.path.join(self.bin, 'iw'), 'SENTINEL_IP': os.path.join(self.bin, 'ip'),
               'SENTINEL_REBOOT': os.path.join(self.bin, 'reboot'), 'SENTINEL_PROC': self.proc}
        shell = [BUSYBOX, 'sh'] if BUSYBOX else ['sh']
        r = subprocess.run(shell + [os.path.join(self.release, script)] + list(args), env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
        return r.returncode, r.stdout.decode()

    # helpers ---------------------------------------------------------------

    @property
    def module(self):
        return os.path.join(self.root, 'pineapple/modules/Sentinel')

    @property
    def data(self):
        return os.path.join(self.root, 'root/.Sentinel')

    def opkg_calls(self):
        try:
            with open(self.fake + '/opkg.log') as fh:
                return fh.read().splitlines()
        except IOError:
            return []

    def commands(self):
        try:
            with open(self.fake + '/commands.log') as fh:
                return [' '.join([os.path.basename(line.split()[0])] + line.split()[1:])
                        for line in fh.read().splitlines()]
        except IOError:
            return []


class InstallTest(InstallTestCase):

    def test_normal_install_with_sqlite_missing(self):
        rc, out = self.run_script('install.sh')
        self.assertEqual(rc, 0, out)
        self.assertTrue(os.path.exists(self.module + '/assets/engine/engine.py'))
        self.assertEqual([c for c in self.opkg_calls() if c.startswith('install')], ['install ./' + IPK])
        self.assertEqual(stat.S_IMODE(os.stat(self.data).st_mode), 0o700)
        self.assertTrue(os.path.exists(self.module + '/uninstall.sh'))
        self.assertIn('Reload the Pineapple web interface', out)

    def test_sqlite_already_present(self):
        self.write(self.fake + '/sqlite_ok', '')
        rc, out = self.run_script('install.sh')
        self.assertEqual(rc, 0, out)
        self.assertFalse(any(c.startswith('install') for c in self.opkg_calls()))

    def test_wrong_archive_checksum_stops_before_anything(self):
        self.release_files(sums={'archive': '0' * 64})
        rc, out = self.run_script('install.sh')
        self.assertNotEqual(rc, 0)
        self.assertIn('checksum mismatch', out)
        self.assertFalse(os.path.exists(self.module))

    def test_wrong_ipk_checksum_never_reaches_opkg(self):
        self.release_files(sums={'ipk': '0' * 64})
        rc, out = self.run_script('install.sh')
        self.assertNotEqual(rc, 0)
        self.assertFalse(any(c.startswith('install') for c in self.opkg_calls()))

    def test_archive_escaping_its_folder_is_refused(self):
        for bad in (('Sentinel/../evil', b'x'), ('other/file', b'x'), ('Sentinel/link', ('link', '/etc/passwd'))):
            self.release_files(entries=GOOD_ARCHIVE + [bad])
            rc, out = self.run_script('install.sh')
            self.assertNotEqual(rc, 0, bad[0])
            self.assertIn('unexpected entry', out)
            self.assertFalse(os.path.exists(self.module), bad[0])
            self.assertFalse(os.path.exists(os.path.join(self.root, 'pineapple/modules/evil')))

    def test_other_python_version_gets_no_ipk(self):
        self.write(self.fake + '/pyver', '3.10')
        rc, out = self.run_script('install.sh')
        self.assertEqual(rc, 0, out)
        self.assertIn('built for Python 3.9', out)
        self.assertFalse(any(c.startswith('install') for c in self.opkg_calls()))
        self.assertTrue(os.path.exists(self.module))

    def test_other_architecture_gets_no_ipk(self):
        self.write(self.fake + '/arch', 'arch all 1\narch aarch64_cortex-a53 10\n')
        rc, out = self.run_script('install.sh')
        self.assertEqual(rc, 0, out)
        self.assertIn('built for mipsel_24kc', out)
        self.assertFalse(any(c.startswith('install') for c in self.opkg_calls()))

    def test_running_twice_changes_nothing(self):
        self.assertEqual(self.run_script('install.sh')[0], 0)
        self.write(self.data + '/settings.json', '{"dwell_ms": 900}')
        rc, out = self.run_script('install.sh')
        self.assertEqual(rc, 0, out)
        with open(self.data + '/settings.json') as fh:
            self.assertEqual(fh.read(), '{"dwell_ms": 900}')
        self.assertEqual(len([c for c in self.opkg_calls() if c.startswith('install')]), 1)

    def test_upgrade_keeps_settings_and_data_and_asks_for_a_reboot(self):
        os.makedirs(self.module)
        self.write(self.module + '/old.py', 'old version')
        os.makedirs(self.data)
        self.write(self.data + '/settings.json', '{"track_clients": false}')
        self.write(self.data + '/sentinel.db', 'database')
        self.write(self.data + '/my_networks.json', '{"networks": []}')
        rc, out = self.run_script('install.sh')
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(self.module + '/old.py'))
        for name, text in (('settings.json', '{"track_clients": false}'), ('sentinel.db', 'database'),
                           ('my_networks.json', '{"networks": []}')):
            with open(self.data + '/' + name) as fh:
                self.assertEqual(fh.read(), text)
        self.assertIn('reboot the Pineapple', out)
        self.assertIn('Ctrl+Shift+R', out)

    def test_reboot_option(self):
        rc, out = self.run_script('install.sh', '--reboot')
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.commands(), ['reboot'])

    def test_unknown_option_is_refused(self):
        rc, out = self.run_script('install.sh', '--force')
        self.assertNotEqual(rc, 0)
        self.assertFalse(os.path.exists(self.module))

    def test_other_python_package_changed_is_a_warning(self):
        self.write(self.fake + '/upgrade_light', '')
        rc, out = self.run_script('install.sh')
        self.assertEqual(rc, 0, out)
        self.assertIn('Other Python packages were changed', out)
        self.assertIn('python3-light - 3.9.16-1', out)

    def test_running_engine_is_stopped_on_upgrade(self):
        proc = subprocess.Popen(['sleep', '60'])
        try:
            os.makedirs(os.path.join(self.proc, str(proc.pid)))
            with open(os.path.join(self.proc, str(proc.pid), 'cmdline'), 'wb') as fh:
                fh.write(b'python3\x00/pineapple/modules/Sentinel/assets/engine/engine.py\x00--db\x00x')
            self.write(self.root + '/tmp/sentinel-engine.pid', str(proc.pid))
            rc, out = self.run_script('install.sh')
            self.assertEqual(rc, 0, out)
            self.assertIsNotNone(proc.wait(timeout=10))  # it was stopped
        finally:
            if proc.poll() is None:
                proc.kill()


class UninstallTest(InstallTestCase):

    def setUp(self):
        super(UninstallTest, self).setUp()
        self.assertEqual(self.run_script('install.sh')[0], 0)
        self.write(self.data + '/settings.json', '{}')

    def test_uninstall_keeps_data_and_package_by_default(self):
        rc, out = self.run_script('uninstall.sh')
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(self.module))
        self.assertTrue(os.path.exists(self.data + '/settings.json'))
        self.assertFalse(any(c.startswith('remove') for c in self.opkg_calls()))
        self.assertIn('--purge', out)

    def test_purge_and_remove_sqlite(self):
        rc, out = self.run_script('uninstall.sh', '--purge', '--remove-sqlite')
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(self.data))
        self.assertIn('remove python3-sqlite3', self.opkg_calls())

    def test_pid_of_another_process_is_never_signalled(self):
        proc = subprocess.Popen(['sleep', '60'])
        try:
            os.makedirs(os.path.join(self.proc, str(proc.pid)))
            with open(os.path.join(self.proc, str(proc.pid), 'cmdline'), 'wb') as fh:
                fh.write(b'sleep\x0060')
            self.write(self.root + '/tmp/sentinel-engine.pid', str(proc.pid))
            rc, out = self.run_script('uninstall.sh')
            self.assertEqual(rc, 0, out)
            self.assertIn('no signal sent', out)
            time.sleep(0.3)
            self.assertIsNone(proc.poll())  # still running
        finally:
            proc.kill()

    def test_radio_changes_are_undone_but_never_wlan1mon(self):
        self.write(self.root + '/tmp/sentinel-radios.json',
                   '{"created": ["wlan3mon", "wlan1mon"], "downed": ["wlan3"]}')
        rc, out = self.run_script('uninstall.sh')
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.commands(), ['iw dev wlan3mon del', 'ip link set wlan3 up'])
        self.assertFalse(os.path.exists(self.root + '/tmp/sentinel-radios.json'))

    def test_strange_interface_names_are_ignored(self):
        self.write(self.root + '/tmp/sentinel-radios.json',
                   '{"created": ["wlan3mon; reboot", "$(reboot)"], "downed": []}')
        rc, out = self.run_script('uninstall.sh')
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.commands(), [])


class SyntaxTest(unittest.TestCase):

    def test_scripts_parse(self):
        shells = [[BUSYBOX, 'sh']] if BUSYBOX else []
        shells += [[s] for s in ('dash', 'sh') if shutil.which(s)]
        for script in ('install.sh', 'uninstall.sh', 'install-from-pc.sh'):
            for shell in shells:
                r = subprocess.run(shell + ['-n', os.path.join(INSTALLER, script)],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                self.assertEqual(r.returncode, 0, '%s %s: %s' % (shell, script, r.stdout))


if __name__ == '__main__':
    if not BUSYBOX:
        print('BusyBox not found: the scripts run with the system shell and tools', file=sys.stderr)
    unittest.main(verbosity=1)
