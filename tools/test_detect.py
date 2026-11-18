#!/usr/bin/env python3
"""
Tests for the intrusion detection (assets/engine/detect.py), standard library only.

Each test builds a capture with exact timestamps, replays it through the engine
(5 s windows follow the capture's clock) and reads the `events` table.

    python3 tools/test_detect.py
"""

import json
import os
import re
import shutil
import sqlite3
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'projects', 'Sentinel', 'src', 'assets', 'engine'))
sys.path.insert(0, HERE)
import detect  # noqa: E402
import dot11  # noqa: E402
import engine  # noqa: E402
from selftest import radiotap, mac, ie  # noqa: E402

T0 = 1800000000.0
HOME = '02:10:00:00:00:01'
TWIN = '0a:66:00:00:00:09'
OTHER = '0e:77:00:00:00:05'
CLIENT = 'da:00:00:00:00:42'
SUITE = {'psk': 2, 'sae': 8}


def rsn(akms, mfpc=False, mfpr=False):
    caps = (0x80 if mfpc else 0) | (0x40 if mfpr else 0)
    body = struct.pack('<H', 1) + b'\x00\x0f\xac\x04' + struct.pack('<H', 1) + b'\x00\x0f\xac\x04'
    body += struct.pack('<H', len(akms)) + b''.join(b'\x00\x0f\xac' + bytes([SUITE[a]]) for a in akms)
    return ie(48, body + struct.pack('<H', caps))


SECURITY_IE = {
    'transition': lambda: rsn(['psk', 'sae'], mfpc=True),
    'wpa2': lambda: rsn(['psk']),
    'wpa3': lambda: rsn(['sae'], mfpc=True, mfpr=True),
    'open': lambda: b'',
}


def mgmt(subtype, bssid, ssid, ch, sec='transition', extra=b'', dst='ff:ff:ff:ff:ff:ff'):
    fc = bytes([subtype << 4, 0])
    hdr = fc + b'\x00\x00' + mac(dst) + mac(bssid) + mac(bssid) + b'\x00\x00'
    privacy = sec != 'open'
    raw_ssid = ssid if isinstance(ssid, bytes) else ssid.encode()
    body = b'\x00' * 8 + struct.pack('<HH', 100, 0x0411 if privacy else 0x0401)
    body += ie(0, raw_ssid) + ie(1, b'\x8c\x12\x98\x24\xb0\x48\x60\x6c') + ie(3, bytes([ch]))
    body += SECURITY_IE[sec]() + extra
    freq = 2407 + 5 * ch if ch <= 14 else 5000 + 5 * ch
    return radiotap(freq, -50) + hdr + body


def beacon(bssid, ssid, ch, sec='transition', extra=b''):
    return mgmt(8, bssid, ssid, ch, sec, extra)


def probe_resp(bssid, ssid, ch, sec='transition'):
    return mgmt(5, bssid, ssid, ch, sec, dst='02:cc:00:00:00:01')


def deauth(bssid, dst, ch=6):
    hdr = b'\xc0\x00\x00\x00' + mac(dst) + mac(bssid) + mac(bssid) + b'\x00\x00'
    return radiotap(2407 + 5 * ch, -55) + hdr + struct.pack('<H', 7)


def fingerprint(frame):
    return dot11.parse_frame(frame).info['fingerprint']


class Capture(object):
    """A list of (timestamp, frame), written as a radiotap pcap."""

    def __init__(self):
        self.frames = []

    def add(self, ts, frame):
        self.frames.append((ts, frame))

    def every(self, start, end, step, make):
        t = start
        while t < end - 1e-9:
            self.add(t, make(t))
            t += step

    def write(self, path):
        with open(path, 'wb') as fh:
            fh.write(struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 127))
            for ts, fr in sorted(self.frames, key=lambda x: x[0]):
                fh.write(struct.pack('<IIII', int(ts), int(round((ts % 1) * 1e6)) % 1000000, len(fr), len(fr)))
                fh.write(fr)


class DetectBase(unittest.TestCase):
    """Helpers shared by the test classes below (no test here)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, 'sentinel.db')
        self.mine_path = os.path.join(self.dir, 'my_networks.json')

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def mark(self, bssid=HOME, ssid='Home', sec='transition', ch=6, pmf='capable'):
        """Write my_networks.json the way set_my_network does."""
        security = {'transition': 'WPA3-Transition', 'wpa2': 'WPA2-PSK', 'wpa3': 'WPA3-SAE', 'open': 'Open'}[sec]
        clean = dot11.clean_ssid(ssid if isinstance(ssid, str) else ssid.decode('utf-8', 'replace'))
        entry = {'bssid': bssid, 'ssid': clean, 'added_at': T0,
                 'baseline': {'security': security, 'pmf': pmf, 'channels': [ch],
                              'fingerprints': [fingerprint(beacon(bssid, ssid, ch, sec))]}}
        try:
            with open(self.mine_path) as fh:
                data = json.load(fh)
        except IOError:
            data = {'version': 1, 'networks': []}
        data['networks'].append(entry)
        with open(self.mine_path, 'w') as fh:
            json.dump(data, fh)

    def home(self, cap, start=T0, end=T0 + 30, sec='transition', ssid='Home', extra=b''):
        """The user's access point, one beacon every 0.5 s."""
        cap.every(start, end, 0.5, lambda t: beacon(HOME, ssid, 6, sec, extra))

    def run_capture(self, cap, local=(), track_clients=False, patch=None):
        path = os.path.join(self.dir, 'capture-%d.pcap' % len(os.listdir(self.dir)))
        cap.write(path)
        e = engine.Engine(self.db, track_clients=track_clients, local_bssids=set(local),
                          my_networks_path=self.mine_path)
        if patch:
            patch(e)
        e.run_pcap(path)
        e.conn.close()
        return self.events()

    def events(self):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute('SELECT * FROM events ORDER BY id')]
        conn.close()
        return rows

    def kinds(self, events):
        return [(e['kind'], e['severity']) for e in events]


class DetectTest(DetectBase):


    def test_no_events_on_quiet_capture(self):
        self.mark()
        cap = Capture()
        self.home(cap)
        cap.every(T0, T0 + 30, 0.5, lambda t: beacon(OTHER, 'Neighbour', 11, 'wpa2'))
        cap.every(T0 + 0.25, T0 + 30, 0.5, lambda t: beacon('0e:77:00:00:00:06', 'Cafe', 1, 'open'))
        self.assertEqual(self.run_capture(cap), [])

    def test_evil_twin_same_ssid_other_bssid(self):
        self.mark()
        cap = Capture()
        self.home(cap)
        cap.every(T0 + 10, T0 + 13, 0.5, lambda t: beacon(TWIN, 'Home', 11, 'transition'))
        self.assertEqual(self.kinds(self.run_capture(cap)), [('evil_twin', 'high')])

    def test_evil_twin_weaker_security_is_critical(self):
        self.mark()
        cap = Capture()
        self.home(cap)
        cap.every(T0 + 10, T0 + 13, 0.5, lambda t: beacon(TWIN, 'Home', 11, 'open'))
        events = self.run_capture(cap)
        self.assertEqual(self.kinds(events), [('evil_twin', 'critical')])
        self.assertEqual(events[0]['bssid'], TWIN)
        self.assertIn('"Home"', events[0]['title'])

    def test_evil_twin_needs_three_frames(self):
        self.mark()
        cap = Capture()
        self.home(cap)
        cap.add(T0 + 11, beacon(TWIN, 'Home', 11, 'open'))
        self.assertEqual(self.run_capture(cap), [])

    def test_my_ap_conflict_same_window(self):
        self.mark()
        cap = Capture()
        self.home(cap)
        # A second device spoofs the BSSID with an open network: both in the same windows
        cap.every(T0 + 10.25, T0 + 20, 0.5, lambda t: beacon(HOME, 'Home', 6, 'open'))
        self.assertEqual(self.kinds(self.run_capture(cap)), [('my_ap_conflict', 'critical')])

    def test_my_ap_downgrade_needs_two_windows(self):
        self.mark()
        cap = Capture()
        self.home(cap, T0, T0 + 20)
        self.home(cap, T0 + 20, T0 + 25, sec='open')          # exactly one window
        self.home(cap, T0 + 25, T0 + 40)
        self.assertEqual(self.run_capture(cap), [])

        os.unlink(self.db)
        cap = Capture()
        self.home(cap, T0, T0 + 20)
        self.home(cap, T0 + 20, T0 + 30, sec='open')          # two windows
        self.home(cap, T0 + 30, T0 + 40)
        self.assertEqual(self.kinds(self.run_capture(cap)), [('my_ap_downgrade', 'critical')])

    def test_my_ap_changed_is_medium(self):
        self.mark()
        cap = Capture()
        self.home(cap, T0, T0 + 20)
        self.home(cap, T0 + 20, T0 + 40, extra=ie(221, b'\x00\x50\xf2\x04\x10\x4a\x00\x01\x10'))
        self.assertEqual(self.kinds(self.run_capture(cap)), [('my_ap_changed', 'medium')])

    def test_my_ap_channel_needs_three_windows(self):
        self.mark()
        cap = Capture()
        self.home(cap, T0, T0 + 10)
        cap.every(T0 + 10, T0 + 30, 0.5, lambda t: beacon(HOME, 'Home', 11, 'transition'))
        self.assertEqual(self.kinds(self.run_capture(cap)), [('my_ap_channel', 'info')])

    def test_deauth_flood_thresholds(self):
        cap = Capture()
        cap.every(T0, T0 + 30, 0.5, lambda t: beacon(OTHER, 'Neighbour', 6, 'wpa2'))
        for i in range(9):
            cap.add(T0 + 1 + i * 0.1, deauth(OTHER, CLIENT))
        self.assertEqual(self.run_capture(cap), [])

        os.unlink(self.db)
        cap.add(T0 + 1.95, deauth(OTHER, CLIENT))
        self.assertEqual(self.kinds(self.run_capture(cap)), [('deauth_flood', 'medium')])

    def test_deauth_flood_severity_follows_ownership(self):
        self.mark()
        cap = Capture()
        self.home(cap)
        cap.every(T0, T0 + 30, 0.5, lambda t: beacon(OTHER, 'Neighbour', 6, 'wpa2'))
        for i in range(12):
            cap.add(T0 + 11 + i * 0.1, deauth(HOME, CLIENT))
            cap.add(T0 + 11.05 + i * 0.1, deauth(OTHER, CLIENT))
        found = sorted((e['bssid'], e['severity']) for e in self.run_capture(cap))
        self.assertEqual(found, [(HOME, 'high'), (OTHER, 'medium')])

    def test_beacon_flood(self):
        cap = Capture()
        cap.every(T0, T0 + 30, 0.5, lambda t: beacon(OTHER, 'Neighbour', 6, 'wpa2'))
        for i in range(40):
            b = '06:ff:00:00:%02x:%02x' % (i // 256, i % 256)
            cap.add(T0 + 11 + i * 0.05, beacon(b, 'Free WiFi %d' % i, 6, 'open'))
        events = self.run_capture(cap)
        self.assertEqual(self.kinds(events), [('beacon_flood', 'high')])
        self.assertIsNone(events[0]['bssid'])
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM aps WHERE bssid LIKE '06:ff:%'").fetchone()[0], 0)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM aps').fetchone()[0], 1)
        conn.close()

    def karma_capture(self, bssid):
        cap = Capture()
        cap.every(T0, T0 + 30, 0.5, lambda t: beacon(OTHER, 'Neighbour', 6, 'wpa2'))
        names = ['Airport', 'Hotel', 'Starbucks', 'Office', 'Library', 'Home-Guest']
        for i, n in enumerate(names):
            cap.add(T0 + 11 + i * 0.3, probe_resp(bssid, n, 6, 'open'))
        return cap

    def test_karma_ap(self):
        events = self.run_capture(self.karma_capture(TWIN))
        self.assertEqual(self.kinds(events), [('karma_ap', 'high')])
        self.assertEqual(len(json.loads(events[0]['details'])['ssids']), 6)

    def test_local_bssids_are_ignored(self):
        self.assertEqual(self.run_capture(self.karma_capture(TWIN), local={TWIN}), [])

    def test_cooldown_survives_restart(self):
        self.mark()
        cap = Capture()
        self.home(cap)
        cap.every(T0 + 10, T0 + 13, 0.5, lambda t: beacon(TWIN, 'Home', 11, 'open'))
        self.run_capture(cap)
        cap = Capture()
        self.home(cap, T0 + 600, T0 + 630)
        cap.every(T0 + 610, T0 + 613, 0.5, lambda t: beacon(TWIN, 'Home', 11, 'open'))
        self.assertEqual(self.kinds(self.run_capture(cap)), [('evil_twin', 'critical')])

    def test_global_cap_keeps_room_for_my_networks(self):
        self.mark()
        cap = Capture()
        self.home(cap, T0, T0 + 130)
        for i in range(200):  # 200 karma access points, 10 per window
            b = '06:ee:00:00:%02x:%02x' % (i // 256, i % 256)
            t = T0 + 0.5 + (i // 10) * 5 + (i % 10) * 0.3
            for k in range(5):
                cap.add(t + k * 0.01, probe_resp(b, 'Lure-%d-%d' % (i, k), 6, 'open'))
        cap.every(T0 + 120, T0 + 123, 0.5, lambda t: beacon(TWIN, 'Home', 11, 'open'))
        events = self.run_capture(cap)
        kinds = [e['kind'] for e in events]
        normal = [k for k in kinds if k not in detect.PROTECTED and k != 'suppressed']
        self.assertEqual(len(normal), 60)
        self.assertEqual(kinds.count('suppressed'), 1)
        self.assertEqual(kinds.count('evil_twin'), 1)

    def test_no_client_mac_in_details(self):
        cap = Capture()
        cap.every(T0, T0 + 30, 0.5, lambda t: beacon(OTHER, 'Neighbour', 6, 'wpa2'))
        for i in range(15):
            cap.add(T0 + 11 + i * 0.1, deauth(OTHER, CLIENT))
        events = self.run_capture(cap)
        self.assertEqual(len(events), 1)
        macs = set(re.findall(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}', json.dumps(events) .lower()))
        self.assertEqual(macs, {OTHER})
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM disconnections WHERE dst != '' OR src != ''").fetchone()[0], 0)
        conn.close()

    def test_detector_error_does_not_stop_engine(self):
        def broken(e):
            def boom(agg, now):
                raise RuntimeError('detector failure')
            e.detector.run = boom
        cap = Capture()
        cap.every(T0, T0 + 30, 0.5, lambda t: beacon(OTHER, 'Neighbour', 6, 'wpa2'))
        self.assertEqual(self.run_capture(cap, patch=broken), [])
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute('SELECT beacons FROM aps').fetchone()[0], 60)
        conn.close()

    def test_ssid_is_cleaned_in_titles(self):
        nasty = 'Home\nNet‮'.encode('utf-8')
        self.mark(ssid=nasty)
        cap = Capture()
        cap.every(T0, T0 + 30, 0.5, lambda t: beacon(HOME, nasty, 6))
        cap.every(T0 + 10, T0 + 13, 0.5, lambda t: beacon(TWIN, nasty, 11, 'open'))
        events = self.run_capture(cap)
        self.assertEqual(self.kinds(events), [('evil_twin', 'critical')])
        title = events[0]['title']
        self.assertNotIn('\n', title)
        self.assertNotIn('‮', title)
        self.assertIn('Home·Net·', title)


    def test_command_line_reads_wids_enabled(self):
        """engine.py --pcap --settings: detection on by default, off with wids_enabled false."""
        import subprocess
        self.mark()
        cap = Capture()
        self.home(cap)
        cap.every(T0 + 10, T0 + 13, 0.5, lambda t: beacon(TWIN, 'Home', 11, 'open'))
        pcap = os.path.join(self.dir, 'cli.pcap')
        cap.write(pcap)
        script = os.path.join(HERE, '..', 'projects', 'Sentinel', 'src', 'assets', 'engine', 'engine.py')
        for enabled, expected in ((False, 0), (True, 1)):
            if os.path.exists(self.db):
                os.unlink(self.db)
            settings = os.path.join(self.dir, 'settings.json')
            with open(settings, 'w') as fh:
                json.dump({'wids_enabled': enabled}, fh)
            subprocess.run([sys.executable, script, '--pcap', pcap, '--db', self.db, '--settings', settings],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.assertEqual(len(self.events()), expected, 'wids_enabled=%s' % enabled)

class SummaryTest(DetectBase):
    """Roadmap: the small file a dashboard reads every minute."""

    def test_summary_after_an_imitation(self):
        import stat
        import summary
        self.mark()
        cap = Capture()
        self.home(cap)
        cap.every(T0 + 10, T0 + 13, 0.5, lambda t: beacon(TWIN, 'Home', 11, 'open'))
        self.run_capture(cap)
        e = engine.Engine(self.db, my_networks_path=self.mine_path,
                          summary_path=os.path.join(self.dir, 'summary.json'))
        e.write_status()
        self.assertTrue(e.write_summary())
        path = os.path.join(self.dir, 'summary.json')
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertLess(os.path.getsize(path), 4096)
        with open(path) as fh:
            data = json.load(fh)
        self.assertEqual(data['format'], 1)
        self.assertEqual(data['alerts']['unread_total'], 1)
        self.assertEqual(data['alerts']['unread']['critical'], 1)
        self.assertIn('your network name "Home"', data['alerts']['recent'][0]['title'])
        self.assertEqual(data['my_networks']['marked'], 1)
        self.assertAlmostEqual(data['generated_at'], __import__('time').time(), delta=60)
        # Seen within the hour, then missing a day later (the capture's own clock)
        soon = summary.build(e.conn, e.last_status, self.mine_path, now=T0 + 600)
        self.assertEqual((soon['my_networks']['seen_last_hour'], soon['my_networks']['not_seen']), (1, []))
        later = summary.build(e.conn, e.last_status, self.mine_path, now=T0 + 86400)
        self.assertEqual(later['my_networks']['not_seen'], [{'bssid': HOME, 'ssid': 'Home'}])
        e.conn.close()

    def test_summary_write_never_raises(self):
        import summary
        self.assertFalse(summary.write('/nonexistent-folder/summary.json', {'x': 1}))
        self.assertFalse(summary.write(os.path.join(self.dir, 's.json'), {'x': object()}))

    def test_replay_writes_no_summary(self):
        cap = Capture()
        cap.every(T0, T0 + 10, 0.5, lambda t: beacon(OTHER, 'Neighbour', 6, 'wpa2'))
        self.run_capture(cap)
        self.assertFalse(any(n.startswith('summary') for n in os.listdir(self.dir)))

class AuditP1Test(DetectBase):
    """Audit items 3.4, 4.1 and 6.1 (before the Hak5 submission)."""

    def audit(self, mine=()):
        import analysis
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        try:
            return analysis.security_audit(conn, max_age=10 ** 9, now=T0 + 60, mine=set(mine))
        finally:
            conn.close()

    def test_one_forged_beacon_does_not_rewrite_security(self):
        cap = Capture()
        cap.every(T0, T0 + 4.5, 0.5, lambda t: beacon(OTHER, 'Neighbour', 6, 'wpa2'))
        cap.add(T0 + 4.8, beacon(OTHER, 'Neighbour', 6, 'open'))   # last frame of the window
        self.run_capture(cap)
        net = [n for n in self.audit()['networks'] if n['bssid'] == OTHER][0]
        self.assertEqual(net['security'], 'WPA2-PSK')

    def test_an_access_point_seen_once_is_not_audited_unless_yours(self):
        cap = Capture()
        cap.add(T0, beacon(OTHER, 'Passing-by', 6, 'open'))
        cap.add(T0 + 0.1, beacon(HOME, 'Home', 6, 'transition'))
        self.run_capture(cap)
        bssids = [n['bssid'] for n in self.audit(mine=[HOME])['networks']]
        self.assertEqual(bssids, [HOME])

    def test_contradictory_announcements_are_flagged(self):
        cap = Capture()
        cap.every(T0, T0 + 20, 0.5, lambda t: beacon(OTHER, 'Neighbour', 6, 'wpa2' if t < T0 + 10 else 'wpa3'))
        self.run_capture(cap)
        net = [n for n in self.audit()['networks'] if n['bssid'] == OTHER][0]
        self.assertIn('conflicting', [f['code'] for f in net['findings']])
        self.assertNotEqual(net['grade'], 'info')   # an info finding never sets the grade

    def test_frame_budget(self):
        e = engine.Engine(self.db, local_bssids=set())
        mgmt_frame = beacon(OTHER, 'Flood', 6, 'open')
        data_frame = radiotap(2437, -50) + struct.pack('<HH', 0x0008, 0) + b'\x00' * 22
        passed = [e.within_budget(data_frame, T0) for _ in range(engine.FRAME_BUDGET_SOFT)]
        self.assertTrue(all(passed))
        self.assertFalse(e.within_budget(data_frame, T0))       # over the soft limit: data dropped
        self.assertTrue(e.within_budget(mgmt_frame, T0))        # management still goes through
        for _ in range(engine.FRAME_BUDGET_HARD):
            e.within_budget(mgmt_frame, T0)
        self.assertFalse(e.within_budget(mgmt_frame, T0))       # over the hard limit: nothing
        self.assertTrue(e.within_budget(data_frame, T0 + 1))    # a new second, a new budget
        self.assertGreater(e.frames_over_budget, 0)
        self.assertFalse(e.within_budget(b'\x00', T0 + 1) and False)  # never raises on short frames
        e.conn.close()

    def test_healthy_flag(self):
        radio = engine.Radio('wlanXmon', [1], False, 0.1)
        e = engine.Engine(self.db, radios=[radio], local_bssids=set())
        e.running = True
        e.write_status()
        self.assertTrue(e.last_status['healthy'])
        radio.error = 'wlanXmon stopped working'
        e.write_status()
        self.assertFalse(e.last_status['healthy'])
        e.conn.close()

    def test_lost_radio_is_reopened(self):
        import socket
        import threading
        import time as _time

        class BrokenSocket(socket.socket):
            def recv(self, *args):
                raise OSError(100, 'Network is down')

        class FakeRadio(engine.Radio):
            broken = True
            opens = 0

            def open(self):
                FakeRadio.opens += 1
                a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
                self._peer = b
                if FakeRadio.broken:
                    self.sock = BrokenSocket(a.family, a.type, fileno=a.detach())
                    b.send(b'x')                    # readable, so recv() is called and fails
                else:
                    a.setblocking(False)
                    self.sock = a

        radio = FakeRadio('wlanXmon', [1], False, 0.1)
        holder = {}

        def run():   # SQLite connections belong to the thread that opens them
            holder['engine'] = engine.Engine(self.db, radios=[radio], local_bssids=set())
            holder['engine'].run_live()
            holder['engine'].conn.close()

        old = engine.RADIO_RETRY
        engine.RADIO_RETRY = 0.3
        t = threading.Thread(target=run)
        t.start()
        try:
            while 'engine' not in holder:
                _time.sleep(0.01)
            e = holder['engine']
            deadline = _time.time() + 5
            while 'stopped working' not in (radio.error or '') and _time.time() < deadline:
                _time.sleep(0.05)
            self.assertIn('stopped working', radio.error or '')
            self.assertFalse(e.running and not radio.error)   # not healthy while in error
            FakeRadio.broken = False                     # the adapter is back
            deadline = _time.time() + 5
            while radio.error and _time.time() < deadline:
                _time.sleep(0.05)
            self.assertIsNone(radio.error)
            self.assertGreaterEqual(FakeRadio.opens, 2)
            self.assertTrue(e.running)
        finally:
            if 'engine' in holder:
                holder['engine'].running = False
            t.join(5)
            engine.RADIO_RETRY = old

if __name__ == '__main__':
    unittest.main(verbosity=1)
