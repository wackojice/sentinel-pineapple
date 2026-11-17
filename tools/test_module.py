#!/usr/bin/env python3
"""
Regression tests for the Sentinel module backend (module.py). Standard library
only: the Pineapple's own `pineapple` package is replaced by a small stand-in,
and the radios, `iw` and `ip` are simulated, so the tests run on any computer.

    python3 tools/test_module.py
"""

import json
import os
import sys
import tempfile
import time
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', 'projects', 'Sentinel', 'src')


# --------------------------------------------------------------------------
# Stand-in for the `pineapple` package that only exists on the device
# --------------------------------------------------------------------------

class FakeModule(object):
    def __init__(self, name, level):
        self.name = name
        self.handlers = {}
        self.logger = types.SimpleNamespace(info=lambda *a: None)

    def handles_action(self, action):
        def register(fn):
            self.handlers[action] = fn
            return fn
        return register

    def on_start(self):
        return lambda fn: fn

    def send_notification(self, message, level):
        return True


def install_pineapple_stub():
    def package(name, **attrs):
        mod = types.ModuleType(name)
        mod.__dict__.update(attrs)
        sys.modules[name] = mod
        return mod
    package('pineapple')
    package('pineapple.modules', Module=FakeModule, Request=type('Request', (), {}))
    package('pineapple.helpers')
    package('pineapple.helpers.opkg_helpers', OpkgJob=object)
    package('pineapple.helpers.notification_helpers', SUCCESS=1, ERROR=2)
    package('pineapple.jobs', JobManager=lambda **kw: None)


install_pineapple_stub()
sys.path.insert(0, SRC)
import module as m  # noqa: E402


class FakeProcess(object):
    """Stands in for the engine process started by subprocess.Popen."""

    def __init__(self, pid=4242):
        self.pid = pid
        self.exit_code = None  # None = still running

    def poll(self):
        return self.exit_code


class FakeRadios(object):
    """
    A simulated set of wireless interfaces that answers the `iw` and `ip`
    commands module.py runs, and records them.
    """

    def __init__(self):
        self.ifaces = {}
        self.commands = []

    def add(self, name, phy, mode='managed', up=True, connected=False):
        self.ifaces[name] = {'phy': phy, 'mode': mode, 'up': up, 'connected': connected}

    def reboot(self):
        """Monitor interfaces vanish and the others come back up."""
        for name in [n for n, i in self.ifaces.items() if i['mode'] == 'monitor']:
            del self.ifaces[name]
        for i in self.ifaces.values():
            i['up'] = True

    def wireless_interfaces(self):
        return [{'name': n, 'phy': i['phy'], 'monitor': i['mode'] == 'monitor',
                 'state': 'up' if i['connected'] else 'down', 'up': i['up'], 'bands': ['2.4', '5']}
                for n, i in sorted(self.ifaces.items())]

    def run(self, args, timeout=10):
        self.commands.append(' '.join(args))
        if args[:2] == ['iw', 'dev'] and args[3] == 'info':
            return 0, 'Interface %s\n\ttype %s\n' % (args[2], self.ifaces[args[2]]['mode'])
        if args[:2] == ['iw', 'dev'] and args[3] == 'link':
            return 0, 'Connected to 02:00:00:00:00:01' if self.ifaces[args[2]]['connected'] \
                else 'Not connected.\n'
        if args[:2] == ['iw', 'phy'] and args[3:5] == ['interface', 'add']:
            self.add(args[5], args[2], mode='monitor', up=False)
            return 0, ''
        if args[:3] == ['ip', 'link', 'set']:
            self.ifaces[args[3]]['up'] = args[4] == 'up'
            return 0, ''
        return 1, 'unexpected command'

    def can_hop(self, monitor):
        """What the kernel enforces: no other interface of the radio may be up."""
        phy = self.ifaces[monitor]['phy']
        return not any(i['up'] for n, i in self.ifaces.items()
                       if i['phy'] == phy and n != monitor and i['mode'] != 'monitor')


class ModuleTestCase(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        m.DATA_DIR = self.dir
        m.DB_PATH = os.path.join(self.dir, 'sentinel.db')
        m.SETTINGS_PATH = os.path.join(self.dir, 'settings.json')
        m.PID_PATH = os.path.join(self.dir, 'engine.pid')
        m.LOG_PATH = os.path.join(self.dir, 'engine.log')
        m._engine_proc = None
        m._radio_warnings = {}
        m.RADIO_STATE_PATH = os.path.join(self.dir, 'radios.json')
        m._dep.update(state=None, job_id=None, error=None, warning=None, auto_tried=False, before=None)
        m.AUTO_INSTALL_DEPENDENCIES = False
        self.jobs = []
        test = self

        class FakeJobs(object):
            def execute_job(self, job, callbacks=()):
                test.jobs.append((job, callbacks))
                return 'job-%d' % len(test.jobs)
        m.job_manager = FakeJobs()
        m.OpkgJob = lambda package, install: ('opkg', package, install)
        m._is_engine = lambda pid: True

        self.radios = FakeRadios()
        m._wireless_interfaces = self.radios.wireless_interfaces
        m._run = self.radios.run

        self.process = FakeProcess()
        self.popen_calls = []

        def fake_popen(args, **kw):
            self.popen_calls.append(args)
            return self.process
        m.subprocess.Popen = fake_popen
        m.time.sleep = lambda seconds: None
        m._sqlite_available = lambda: True

    def settings(self, *radios):
        return {'radios': [dict({'enabled': True, 'hopping': True, 'channels': [36, 40]}, **r)
                           for r in radios]}

    def call(self, action, **params):
        request = types.SimpleNamespace(module='Sentinel', action=action, **params)
        return m.module.handlers[action](request)


class FreeRadioTest(ModuleTestCase):
    """Issue #5: wlan3mon cannot change channel while wlan3 (managed) is up."""

    def mk7ac(self, connected=False):
        self.radios.add('wlan3', 'phy3', mode='managed', up=True, connected=connected)
        self.radios.add('wlan3mon', 'phy3', mode='monitor')

    def test_idle_client_interface_is_taken_down(self):
        self.mk7ac()
        self.assertFalse(self.radios.can_hop('wlan3mon'))
        warnings = m._prepare_radios(self.settings({'iface': 'wlan3mon'}))
        self.assertEqual(warnings, {})
        self.assertFalse(self.radios.ifaces['wlan3']['up'])
        self.assertTrue(self.radios.can_hop('wlan3mon'))

    def test_connected_client_interface_is_left_alone_and_reported(self):
        self.mk7ac(connected=True)
        warnings = m._prepare_radios(self.settings({'iface': 'wlan3mon'}))
        self.assertTrue(self.radios.ifaces['wlan3']['up'])
        self.assertIn('wlan3 is in use', warnings['wlan3mon'])

    def test_access_point_is_never_taken_down(self):
        self.radios.add('wlan0', 'phy0', mode='AP', up=True)
        self.radios.add('wlan0mon', 'phy0', mode='monitor')
        warnings = m._prepare_radios(self.settings({'iface': 'wlan0mon'}))
        self.assertTrue(self.radios.ifaces['wlan0']['up'])
        self.assertIn('wlan0mon', warnings)
        self.assertFalse(any(c.startswith('ip link set wlan0 ') for c in self.radios.commands))

    def test_other_radios_are_not_touched(self):
        self.mk7ac()
        self.radios.add('wlan2', 'phy2', mode='managed', up=True)
        m._prepare_radios(self.settings({'iface': 'wlan3mon'}))
        self.assertTrue(self.radios.ifaces['wlan2']['up'])

    def test_nothing_is_taken_down_when_the_radio_does_not_hop(self):
        self.mk7ac()
        m._prepare_radios(self.settings({'iface': 'wlan3mon', 'hopping': False}))
        self.assertTrue(self.radios.ifaces['wlan3']['up'])

    def test_after_a_reboot_the_monitor_is_recreated_and_the_radio_freed_again(self):
        self.mk7ac()
        settings = self.settings({'iface': 'wlan3mon'})
        m._prepare_radios(settings)
        self.radios.reboot()
        self.assertNotIn('wlan3mon', self.radios.ifaces)
        self.assertTrue(self.radios.ifaces['wlan3']['up'])

        m._prepare_radios(settings)
        self.assertIn('wlan3mon', self.radios.ifaces)
        self.assertTrue(self.radios.can_hop('wlan3mon'))

    def test_a_missing_iw_or_ip_command_does_not_raise(self):
        self.mk7ac()
        m._run = lambda args, timeout=10: (1, 'No such file or directory')
        warnings = m._prepare_radios(self.settings({'iface': 'wlan3mon'}))
        self.assertIn('wlan3mon', warnings)  # could not be freed, and said so


class StartTest(ModuleTestCase):
    """Issue #4: a start that takes 4 to 6 s is not a failed start."""

    def setUp(self):
        super(StartTest, self).setUp()
        self.radios.add('wlan1mon', 'phy1', mode='monitor')
        with open(m.SETTINGS_PATH, 'w') as fh:
            json.dump(self.settings({'iface': 'wlan1mon'}), fh)

    def test_slow_engine_is_reported_as_starting_not_as_failed(self):
        # The engine has not written anything yet: no PID file of its own, no heartbeat
        message, ok = self.call('start_engine')
        self.assertTrue(ok, message)
        self.assertEqual(message, 'Monitoring is starting')
        status = self.call('get_status')
        self.assertEqual((status['state'], status['running'], status['healthy']),
                         ('starting', True, False))

    def test_engine_that_exits_at_once_is_reported_as_failed(self):
        self.process.exit_code = 1
        with open(m.LOG_PATH, 'w') as fh:
            fh.write('Interface wlan1mon does not exist\n')
        message, ok = self.call('start_engine')
        self.assertFalse(ok)
        self.assertIn('Interface wlan1mon does not exist', message)
        self.assertEqual(self.call('get_status')['state'], 'stopped')
        self.assertFalse(os.path.exists(m.PID_PATH))

    def test_status_carries_the_pineapple_clock(self):
        # The page measures "x min ago" on the Pineapple's clock (no RTC, often no Internet)
        status = self.call('get_status')
        self.assertAlmostEqual(status['server_time'], time.time(), delta=5)

    def test_engine_that_dies_later_is_reported_as_stopped(self):
        self.call('start_engine')
        self.process.exit_code = 1
        status = self.call('get_status')
        self.assertEqual((status['state'], status['running']), ('stopped', False))

    def test_start_is_not_repeated_while_the_engine_runs(self):
        self.call('start_engine')
        self.call('start_engine')
        self.assertEqual(len(self.popen_calls), 1)


class StateTest(ModuleTestCase):
    """Issue #6: the header must not say "Listening" from an old status."""

    def state(self, pid, engine, launched_ago=0):
        with open(m.PID_PATH, 'w') as fh:
            fh.write(str(pid or 0))
        past = time.time() - launched_ago
        os.utime(m.PID_PATH, (past, past))
        return m._engine_state(pid, engine)

    def test_no_process_is_stopped_even_with_a_fresh_looking_status(self):
        engine = {'pid': 4242, 'running': True, 'heartbeat': time.time()}
        self.assertEqual(self.state(None, engine), 'stopped')

    def test_recent_heartbeat_of_the_running_process_is_listening(self):
        engine = {'pid': 4242, 'running': True, 'heartbeat': time.time() - 6}
        self.assertEqual(self.state(4242, engine), 'listening')

    def test_heartbeat_of_an_earlier_run_does_not_count(self):
        engine = {'pid': 1111, 'running': True, 'heartbeat': time.time() - 1}
        self.assertEqual(self.state(4242, engine, launched_ago=2), 'starting')

    def test_old_heartbeat_is_stalled_once_the_start_delay_is_over(self):
        engine = {'pid': 4242, 'running': True, 'heartbeat': time.time() - 120}
        self.assertEqual(self.state(4242, engine, launched_ago=300), 'stalled')

    def test_no_heartbeat_yet_is_starting_then_stalled(self):
        self.assertEqual(self.state(4242, {}, launched_ago=5), 'starting')
        self.assertEqual(self.state(4242, {}, launched_ago=m.START_GRACE + 5), 'stalled')


class SaveSettingsTest(ModuleTestCase):
    """Issue #6: a radio saved with a non-monitor interface could never listen."""

    def test_managed_interface_is_replaced_by_its_monitor_interface(self):
        self.radios.add('wlan1mon', 'phy1', mode='monitor')
        self.radios.add('wlan3', 'phy3', mode='managed')
        result = self.call('save_settings', settings=self.settings(
            {'iface': 'wlan1mon', 'channels': [1, 6, 11]}, {'iface': 'wlan3'}))
        self.assertEqual([r['iface'] for r in result['settings']['radios']],
                         ['wlan1mon', 'wlan3mon'])
        self.assertEqual(self.radios.ifaces['wlan3mon']['mode'], 'monitor')
        with open(m.SETTINGS_PATH) as fh:
            self.assertEqual(json.load(fh)['radios'][1]['iface'], 'wlan3mon')

    def test_same_radio_chosen_twice_is_refused(self):
        self.radios.add('wlan3', 'phy3', mode='managed')
        self.radios.add('wlan3mon', 'phy3', mode='monitor')
        result = self.call('save_settings', settings=self.settings(
            {'iface': 'wlan3mon'}, {'iface': 'wlan3'}))
        self.assertEqual(result, ('Both radios use the same interface', False))

    def test_monitor_interface_that_cannot_be_created_is_an_error(self):
        self.radios.add('wlan3', 'phy3', mode='managed')
        m._run = lambda args, timeout=10: (1, 'command failed: Operation not supported (-95)')
        result = self.call('save_settings', settings=self.settings({'iface': 'wlan3'}))
        self.assertEqual(result, ('Could not create a monitor interface for wlan3', False))
        self.assertFalse(os.path.exists(m.SETTINGS_PATH))


class DataDirTest(ModuleTestCase):
    """Audit 2.1: nothing created /root/.Sentinel; it must exist, root only."""

    def test_saving_settings_creates_the_data_folder_root_only(self):
        m.DATA_DIR = os.path.join(self.dir, 'fresh', '.Sentinel')
        m.SETTINGS_PATH = os.path.join(m.DATA_DIR, 'settings.json')
        m._save_settings(m.DEFAULT_SETTINGS)
        self.assertTrue(os.path.exists(m.SETTINGS_PATH))
        self.assertEqual(os.stat(m.DATA_DIR).st_mode & 0o777, 0o700)


class MyNetworksTest(ModuleTestCase):
    """Roadmap 4: the access points the user marks as theirs."""

    def setUp(self):
        super(MyNetworksTest, self).setUp()
        import store
        conn = store.connect(m.DB_PATH)
        now = time.time()
        rows = [  # bssid, ssid, security, pmf, channel, beacons
            ('02:10:00:00:00:01', 'Home', 'WPA3-Transition', 'capable', 1, 50),
            ('02:10:00:00:00:02', 'Home', 'WPA3-Transition', 'capable', 36, 50),   # same prefix
            ('06:99:00:00:00:03', 'Home', 'WPA3-Transition', 'capable', 6, 50),    # shares a fingerprint
            ('0a:99:00:00:00:04', 'Home', 'Open', 'none', 11, 50),                  # weaker: not suggested
            ('02:10:00:00:00:05', 'Home', 'WPA3-Transition', 'capable', 44, 5),     # too few beacons
            ('0e:99:00:00:00:06', 'Other', 'WPA2-PSK', 'none', 6, 50),
        ]
        with conn:
            for b, ssid, sec, pmf, ch, beacons in rows:
                conn.execute('INSERT INTO aps (bssid, ssid, security, pmf, channel, band, first_seen, '
                             'last_seen, beacons, rssi_last) VALUES (?,?,?,?,?,?,?,?,?,?)',
                             (b, ssid, sec, pmf, ch, '2.4' if ch < 15 else '5', now - 600, now, beacons, -50))
            for b, fp in (('02:10:00:00:00:01', 'fp-home'), ('06:99:00:00:00:03', 'fp-home')):
                conn.execute('INSERT INTO ap_fingerprints VALUES (?,?,?,?,?)', (b, fp, now - 600, now, 30))
        conn.close()

    def test_marking_freezes_a_reference(self):
        result = self.call('set_my_network', bssid='02:10:00:00:00:01', mine=True)
        entry = result['networks'][0]
        self.assertEqual((entry['bssid'], entry['ssid']), ('02:10:00:00:00:01', 'Home'))
        self.assertEqual(entry['baseline'], {'security': 'WPA3-Transition', 'pmf': 'capable',
                                             'channels': [1], 'fingerprints': ['fp-home']})
        self.assertEqual(len(self.call('get_my_networks')['networks']), 1)
        self.call('set_my_network', bssid='02:10:00:00:00:01', mine=False)
        self.assertEqual(self.call('get_my_networks')['networks'], [])

    def test_invalid_requests_are_refused(self):
        refuse = lambda **kw: self.call('set_my_network', **kw)[1]  # noqa: E731
        self.assertFalse(refuse(bssid='not-a-mac', mine=True))
        self.assertFalse(refuse(bssid='02:10:00:00:00:01', mine='true'))  # not a real boolean
        self.assertFalse(refuse(bssid='02:10:00:00:00:99', mine=True))    # unknown
        self.assertFalse(refuse(bssid='02:10:00:00:00:05', mine=True))    # too few beacons
        self.assertFalse(refuse(bssid=None, mine=True))
        self.assertEqual(self.call('get_my_networks')['networks'], [])

    def test_upper_case_bssid_is_accepted(self):
        result = self.call('set_my_network', bssid='02:10:00:00:00:01'.upper(), mine=True)
        self.assertEqual(result['networks'][0]['bssid'], '02:10:00:00:00:01')

    def test_at_most_64_networks(self):
        import mynets
        entries = dict(('02:20:00:00:00:%02x' % i, {'bssid': '02:20:00:00:00:%02x' % i, 'ssid': 'x',
                                                   'added_at': 0, 'baseline': {'channels': []}})
                       for i in range(64))
        mynets.save(m._mynets_path(), entries)
        self.assertEqual(len(mynets.load(m._mynets_path())), 64)
        message, ok = self.call('set_my_network', bssid='02:10:00:00:00:01', mine=True)
        self.assertFalse(ok)

    def test_list_survives_clear_data(self):
        self.call('set_my_network', bssid='02:10:00:00:00:01', mine=True)
        self.call('clear_data')
        self.assertFalse(os.path.exists(m.DB_PATH))
        self.assertEqual(len(self.call('get_my_networks')['networks']), 1)

    def test_damaged_file_is_an_empty_list(self):
        for content in ('{not json', '[]', '{"networks": "x"}', '{"networks": [{"bssid": "zz"}]}'):
            with open(m._mynets_path(), 'w') as fh:
                fh.write(content)
            self.assertEqual(self.call('get_my_networks')['networks'], [])

    def test_suggestions_need_same_ssid_and_security_and_a_link(self):
        self.call('set_my_network', bssid='02:10:00:00:00:01', mine=True)
        found = self.call('suggest_my_networks', bssid='02:10:00:00:00:01')['suggestions']
        self.assertEqual(sorted((s['bssid'], s['reason']) for s in found),
                         [('02:10:00:00:00:02', 'same device'),
                          ('06:99:00:00:00:03', 'same fingerprint')])

    def test_mesh_of_three_access_points_needs_three_stars(self):
        """UniFi-like addresses (fictional): one base address per access point, one variant per network."""
        import store
        conn = store.connect(m.DB_PATH)
        now = time.time()
        rows = []
        for base, ch24, ch5 in (('0c:aa:bb:cc:dd:1', 1, 64), ('ac:11:22:33:44:5', 11, 112), ('ac:11:22:66:77:8', 6, 112)):
            rows += [('0c' + base[2:] + 'e', 'Home', 'WPA3-Transition', ch24),        # 2.4 GHz
                     ('0c' + base[2:] + 'f', 'Home-5G', 'WPA3-Transition', ch5),      # 5 GHz
                     ('22' + base[2:] + 'f', 'Games', 'WPA3-Transition', ch5),
                     ('12' + base[2:] + 'e', 'Guests', 'WPA3-Transition', ch24),
                     ('12' + base[2:] + 'f', 'Guests', 'WPA3-Transition', ch5)]
        with conn:
            for b, ssid, sec, ch in rows:
                conn.execute('INSERT INTO aps (bssid, ssid, security, pmf, channel, band, first_seen, last_seen, '
                             'beacons, rssi_last) VALUES (?,?,?,?,?,?,?,?,?,?)',
                             (b, ssid, sec, 'capable', ch, '2.4' if ch < 15 else '5', now - 600, now, 50, -55))
        conn.close()
        marked = set()

        def star(bssid):
            self.call('set_my_network', bssid=bssid, mine=True)
            marked.add(bssid)
            for s in self.call('suggest_my_networks', bssid=bssid)['suggestions']:
                self.call('set_my_network', bssid=s['bssid'], mine=True)   # the user ticks them all
                marked.add(s['bssid'])

        star('0c:aa:bb:cc:dd:1e')       # first access point, 2.4 GHz network
        self.assertEqual(len(marked), 5)                    # its five networks
        star('0c:11:22:33:44:5e')                           # second access point
        self.assertEqual(len(marked), 11)                   # its five, plus "Home" on the third (same prefix)
        star('0c:11:22:66:77:8f')                           # third access point
        self.assertEqual(len(marked), 15)
        self.assertEqual(len(self.call('get_my_networks')['networks']), 15)

    def test_mark_and_unmark_several_at_once(self):
        r = self.call('set_my_networks', bssids=['02:10:00:00:00:01', '02:10:00:00:00:02', '02:10:00:00:00:05'],
                      mine=True)
        self.assertEqual(sorted(e['bssid'] for e in r['networks']), ['02:10:00:00:00:01', '02:10:00:00:00:02'])
        self.assertEqual(r['refused'], ['02:10:00:00:00:05'])            # too few beacons
        r = self.call('set_my_networks', bssids=['02:10:00:00:00:01'], mine=False)
        self.assertEqual([e['bssid'] for e in r['networks']], ['02:10:00:00:00:02'])

    def test_several_at_once_checks_its_input(self):
        bad = (dict(bssids='02:10:00:00:00:01', mine=True), dict(bssids=['nope'], mine=True),
               dict(bssids=['02:10:00:00:00:01'], mine='yes'), dict(bssids=['02:10:00:00:00:%02x' % i for i in range(65)], mine=False))
        for kw in bad:
            self.assertEqual(self.call('set_my_networks', **kw)[1], False, kw)
        self.assertEqual(self.call('get_my_networks')['networks'], [])

    def test_unmark_all_needs_a_real_confirmation(self):
        self.call('set_my_network', bssid='02:10:00:00:00:01', mine=True)
        self.call('set_my_network', bssid='02:10:00:00:00:02', mine=True)
        for confirm in (None, 'true', 1, False):
            self.assertEqual(self.call('clear_my_networks', confirm=confirm), ('Confirmation required', False))
        self.assertEqual(len(self.call('get_my_networks')['networks']), 2)
        self.assertEqual(self.call('clear_my_networks', confirm=True)['networks'], [])
        self.assertEqual(self.call('get_my_networks')['networks'], [])

    def test_rebaseline_takes_the_current_state(self):
        import store
        self.call('set_my_network', bssid='02:10:00:00:00:01', mine=True)
        conn = store.connect(m.DB_PATH)
        with conn:
            conn.execute("UPDATE aps SET channel = 11 WHERE bssid = '02:10:00:00:00:01'")
        conn.close()
        result = self.call('rebaseline_my_network', bssid='02:10:00:00:00:01')
        self.assertEqual(result['networks'][0]['baseline']['channels'], [11])
        self.assertFalse(self.call('rebaseline_my_network', bssid='0e:99:00:00:00:06')[1])


class DetectionActionsTest(ModuleTestCase):
    """Roadmap 5.8: detection data for the interface, bounded parameters."""

    def setUp(self):
        super(DetectionActionsTest, self).setUp()
        import store
        conn = store.connect(m.DB_PATH)
        with conn:
            for i in range(3):
                store.add_event(conn, 'wids', 'deauth_flood', 'medium', 'Burst %d' % i, bssid='02:00:00:00:00:01')
            store.add_event(conn, 'wids', 'evil_twin', 'critical', 'Twin', bssid='02:00:00:00:00:02')
            store.add_event(conn, 'other', 'note', 'info', 'Not from the detector')
        conn.close()

    def test_get_events_bounds_its_parameters(self):
        for limit in (-5, 0, 10 ** 30, 'abc', None, 2.5):
            self.assertIsInstance(self.call('get_events', limit=limit), list)
        self.assertEqual(len(self.call('get_events', limit=2)), 2)
        self.assertEqual(len(self.call('get_events', source='wids')), 4)
        self.assertEqual(self.call('get_events', source='other')[1], False)

    def test_get_detection(self):
        d = self.call('get_detection')
        self.assertEqual(len(d['events']), 4)
        self.assertEqual(d['unacknowledged'], 4)
        self.assertEqual(d['by_severity'], {'medium': 3, 'critical': 1})
        self.assertTrue(d['enabled'])
        self.call('ack_events')
        self.assertEqual(self.call('get_detection')['unacknowledged'], 0)

    def test_dashboard_shows_only_detector_events(self):
        events = self.call('get_dashboard')['events']
        self.assertEqual(set(e['source'] for e in events), {'wids'})


class SettingsValidationTest(ModuleTestCase):
    """Audit 2.2: switches are strict booleans, numbers bounded."""

    def setUp(self):
        super(SettingsValidationTest, self).setUp()
        self.radios.add('wlan1mon', 'phy1', mode='monitor')

    def save(self, **extra):
        settings = self.settings({'iface': 'wlan1mon', 'channels': [1, 6, 11]})
        settings.update(extra)
        return self.call('save_settings', settings=settings)

    def test_wids_enabled_defaults_to_true_and_is_saved(self):
        self.assertTrue(self.save()['settings']['wids_enabled'])
        self.assertFalse(self.save(wids_enabled=False)['settings']['wids_enabled'])

    def test_non_boolean_switches_are_refused(self):
        for key in ('track_clients', 'track_probes', 'autostart', 'wids_enabled'):
            self.assertEqual(self.save(**{key: 'false'}), ('Invalid value for %s' % key, False))
            self.assertEqual(self.save(**{key: 1}), ('Invalid value for %s' % key, False))

    def test_numbers_are_bounded(self):
        s = self.save(dwell_ms=10 ** 9, channel_window_minutes=-3, audit_max_age_minutes=10 ** 9)['settings']
        self.assertEqual((s['dwell_ms'], s['channel_window_minutes'], s['audit_max_age_minutes']),
                         (5000, 1, 7 * 24 * 60))
        self.assertEqual(self.save(dwell_ms='fast'), ('Invalid settings', False))


class DependencyTest(ModuleTestCase):
    """Installation spec 3: python3-sqlite3, installed with a click by default."""

    def setUp(self):
        super(DependencyTest, self).setUp()
        self.sqlite = False
        m._sqlite_available = lambda: self.sqlite
        self.packages = 'python3-base - 3.9.7-1\npython3-light - 3.9.7-1\nlibsqlite3-0 - 3330000-1\n'
        radios_run = m._run

        def run(args, timeout=10):
            if args[:2] == ['opkg', 'list-installed']:
                return (0, self.packages) if self.packages is not None else (1, 'opkg: not found')
            return radios_run(args, timeout)
        m._run = run

    def finish(self, ok=True, error=None):
        job, callbacks = self.jobs[-1]
        if ok:
            self.sqlite = True
        for cb in callbacks:
            cb(types.SimpleNamespace(was_successful=ok, error=error))

    def deps(self):
        return self.call('get_status')['dependencies']

    def test_present_means_no_job(self):
        self.sqlite = True
        self.assertEqual(self.deps()['state'], 'ok')
        self.assertEqual(self.jobs, [])

    def test_missing_waits_for_a_click_by_default(self):
        for _ in range(3):
            self.assertEqual(self.deps()['state'], 'missing')
        self.assertEqual(self.jobs, [])
        self.call('install_dependencies')
        self.assertEqual((len(self.jobs), self.deps()['state']), (1, 'installing'))

    def test_automatic_install_starts_once(self):
        m.AUTO_INSTALL_DEPENDENCIES = True
        self.assertEqual(self.deps()['state'], 'installing')
        for _ in range(10):
            self.deps()
        self.assertEqual(len(self.jobs), 1)
        self.assertEqual(self.jobs[0][0], ('opkg', 'python3-sqlite3', True))

    def test_second_click_while_installing_starts_nothing(self):
        self.call('install_dependencies')
        self.call('install_dependencies')
        self.assertEqual(len(self.jobs), 1)

    def test_successful_install(self):
        self.call('install_dependencies')
        self.packages += 'python3-sqlite3 - 3.9.16-1\n'
        self.finish(ok=True)
        d = self.deps()
        self.assertEqual((d['state'], d['warning'], d['sqlite']), ('ok', None, True))

    def test_failed_install_is_reported_and_not_retried(self):
        m.AUTO_INSTALL_DEPENDENCIES = True
        self.deps()
        self.finish(ok=False, error='wget returned 4: no network')
        for _ in range(5):
            d = self.deps()
        self.assertEqual((d['state'], d['error']), ('failed', 'wget returned 4: no network'))
        self.assertEqual(len(self.jobs), 1)

    def test_other_python_package_changing_is_a_warning(self):
        self.call('install_dependencies')
        self.packages = ('python3-base - 3.9.7-1\npython3-light - 3.9.16-1\nlibsqlite3-0 - 3330000-1\n'
                         'python3-sqlite3 - 3.9.16-1\n')
        self.finish(ok=True)
        self.assertIn('python3-light 3.9.16-1', self.deps()['warning'])

    def test_opkg_failing_gives_no_warning_and_no_exception(self):
        self.packages = None
        self.call('install_dependencies')
        self.finish(ok=True)
        self.assertIsNone(self.deps()['warning'])

    def test_job_manager_failure_does_not_break_the_status(self):
        m.AUTO_INSTALL_DEPENDENCIES = True

        class Broken(object):
            def execute_job(self, job, callbacks=()):
                raise RuntimeError('job manager not ready')
        m.job_manager = Broken()
        d = self.deps()
        self.assertEqual(d['state'], 'failed')
        self.assertIn('job manager not ready', d['error'])


class RadioStateTest(ModuleTestCase):
    """Audit 3.1: what Sentinel changes on the radios is remembered and undone."""

    def test_taken_down_interfaces_come_back_up_when_stopped(self):
        self.radios.add('wlan3', 'phy3', mode='managed', up=True)
        m._prepare_radios({'radios': [{'iface': 'wlan3mon', 'enabled': True, 'hopping': True}]})
        self.assertIn('wlan3mon', self.radios.ifaces)
        self.assertFalse(self.radios.ifaces['wlan3']['up'])
        self.assertEqual(m._radio_state(), {'created': ['wlan3mon'], 'downed': ['wlan3']})
        self.call('stop_engine')
        self.assertTrue(self.radios.ifaces['wlan3']['up'])
        self.assertEqual(m._radio_state(), {'created': ['wlan3mon'], 'downed': []})

    def test_damaged_state_file_is_ignored(self):
        with open(m.RADIO_STATE_PATH, 'w') as fh:
            fh.write('{broken')
        self.assertEqual(m._radio_state(), {'created': [], 'downed': []})


class DashboardTest(ModuleTestCase):
    """Issue #1: the Overview needs to know when a 0 only means "tracking is off"."""

    def tracking(self, **saved):
        with open(m.SETTINGS_PATH, 'w') as fh:
            json.dump(saved, fh)
        return self.call('get_dashboard')['tracking']

    def test_tracking_is_reported_off_by_default(self):
        self.assertEqual(self.tracking(), {'clients': False, 'probes': False})

    def test_tracking_follows_the_settings(self):
        self.assertEqual(self.tracking(track_clients=True), {'clients': True, 'probes': False})
        self.assertEqual(self.tracking(track_probes=True), {'clients': False, 'probes': True})


if __name__ == '__main__':
    unittest.main(verbosity=1)
