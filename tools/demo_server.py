#!/usr/bin/env python3
"""
Demo backend for screenshots: runs the real module.py (with the stand-in for the
Pineapple's `pineapple` package from test_module.py) on a synthetic capture of
fictional networks, and answers the web interface's API calls.

    python3 tools/demo_server.py &                       # API on 127.0.0.1:8765
    npx ng serve demo                                    # UI on http://localhost:4300

Standard library only. Nothing here talks to a radio.
"""

import json
import os
import random
import struct
import subprocess
import sys
import tempfile
import time
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_module  # noqa: E402  installs the stand-in and imports module.py
from selftest import radiotap, mac, ie, probe_req, data_to_ap, deauth, write_pcap  # noqa: E402

m = test_module.m
random.seed(7)

# Fictional networks: (bssid, ssid, channel, security, rssi)
NETWORKS = [
    ('02:10:00:00:00:01', 'Smith-Home', 1, 'transition', -42),
    ('02:10:00:00:00:02', 'Smith-Home-5G', 36, 'transition', -48),
    ('02:10:00:00:00:03', 'Workshop', 6, 'wpa2', -61),
    ('02:10:00:00:00:04', 'Corner-Cafe', 11, 'open', -74),
    ('02:10:00:00:00:05', 'Office-Lab', 112, 'wpa3', -55),
    ('02:10:00:00:00:06', 'Neighbor-2F', 6, 'wpa2', -80),
    ('02:10:00:00:00:07', 'HP-Printer', 11, 'wpa2-wps', -69),
    ('02:10:00:00:00:08', 'OldRouter', 1, 'wep', -83),
    ('02:10:00:00:00:09', 'Guests', 149, 'owe', -66),
    ('02:10:00:00:00:0a', '', 64, 'wpa2', -77),            # hidden
    ('02:10:00:00:00:0b', 'Apt-304', 44, 'wpa2', -71),
    ('02:10:00:00:00:0c', 'Apt-304', 11, 'wpa2', -79),
]

SUITE = {'psk': 2, 'sae': 8, 'owe': 18}


def rsn(akms, mfpc=False, mfpr=False):
    caps = (0x80 if mfpc else 0) | (0x40 if mfpr else 0)
    body = struct.pack('<H', 1) + b'\x00\x0f\xac\x04' + struct.pack('<H', 1) + b'\x00\x0f\xac\x04'
    body += struct.pack('<H', len(akms)) + b''.join(b'\x00\x0f\xac' + bytes([SUITE[a]]) for a in akms)
    return ie(48, body + struct.pack('<H', caps))


def beacon(bssid, ssid, ch, sec):
    privacy = sec != 'open'
    hdr = b'\x80\x00\x00\x00' + b'\xff' * 6 + mac(bssid) + mac(bssid) + b'\x00\x00'
    body = b'\x00' * 8 + struct.pack('<HH', 100, 0x0411 if privacy else 0x0401)
    body += ie(0, ssid.encode()) + ie(1, b'\x8c\x12\x98\x24\xb0\x48\x60\x6c') + ie(3, bytes([ch]))
    body += {
        'transition': rsn(['psk', 'sae'], mfpc=True),
        'wpa2': rsn(['psk']), 'wpa2-wps': rsn(['psk']),
        'wpa3': rsn(['sae'], mfpc=True, mfpr=True),
        'owe': rsn(['owe'], mfpc=True, mfpr=True),
    }.get(sec, b'')
    if sec == 'wpa2-wps':
        body += ie(221, b'\x00\x50\xf2\x04' + b'\x10\x4a\x00\x01\x10')
    return hdr + body


def freq(ch):
    return 2407 + 5 * ch if ch <= 14 else 5000 + 5 * ch


def build_capture(path, start, end, attacks=False):
    """Rounds of beacons every 10 s between `start` and `end`; with `attacks`, a few
    incidents for the Detection tab."""
    frames = []
    t = start
    while t < end:
        for b, s, ch, sec, rssi in NETWORKS:
            if ch > 14 and os.environ.get('SENTINEL_DEMO_ADAPTER') == 'none':
                continue  # nothing on 5 GHz without an adapter
            frames.append((t + random.random(), radiotap(freq(ch), rssi + random.randint(-3, 3)) + beacon(b, s, ch, sec)))
            # Some data traffic, heavier on the busy channels
            for _ in range({1: 6, 6: 9, 11: 4, 36: 3}.get(ch, 1)):
                frames.append((t + random.random(), radiotap(freq(ch), rssi) + data_to_ap('02:20:00:00:00:%02x' % random.randint(1, 30), b)))
        frames.append((t + 0.5, radiotap(freq(6), -60) + probe_req('02:30:00:00:00:01', 'Hotel-Lobby')))
        t += 10
    if attacks:
        # An open copy of "Smith-Home" on another channel
        for j in range(8):
            frames.append((end - 400 + j * 0.5, radiotap(freq(11), -58) + beacon('0a:66:00:00:00:09', 'Smith-Home', 11, 'open')))
        # Deauthentication bursts: on a neighbour, then on your network
        for j in range(40):
            frames.append((end - 300 + j * 0.05, radiotap(freq(6), -58) + deauth('02:10:00:00:00:03', '02:20:00:00:00:05')))
        for j in range(25):
            frames.append((end - 100 + j * 0.05, radiotap(freq(1), -52) + deauth('02:10:00:00:00:01', 'ff:ff:ff:ff:ff:ff')))
        # One access point that answers for every name it is asked for
        for j, name in enumerate(['Airport-Free', 'Hotel-Guest', 'Cafe-Wifi', 'Library', 'Office-5G', 'Gym']):
            frames.append((end - 200 + j * 0.3, radiotap(freq(6), -63) + b'\x50' + beacon('0e:55:00:00:00:07', name, 6, 'open')[1:]))
    frames.sort()
    with open(path, 'wb') as fh:
        fh.write(struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 127))
        for t, fr in frames:
            fh.write(struct.pack('<IIII', int(t), int((t % 1) * 1e6), len(fr), len(fr)))
            fh.write(fr)


def prepare(tmp):
    m.DATA_DIR = tmp
    m.DB_PATH = os.path.join(tmp, 'sentinel.db')
    m.SETTINGS_PATH = os.path.join(tmp, 'settings.json')
    m.PID_PATH = os.path.join(tmp, 'engine.pid')
    m.LOG_PATH = os.path.join(tmp, 'engine.log')
    now = time.time()
    pcap = os.path.join(tmp, 'demo.pcap')
    # First 10 minutes: the neighbourhood as usual
    build_capture(pcap, now - 1200, now - 600)
    subprocess.run([sys.executable, m.ENGINE, '--pcap', pcap, '--db', m.DB_PATH], check=True,
                   stdout=subprocess.DEVNULL)
    # Mark the two access points of "Smith-Home" as the user's own
    import mynets
    import store
    conn = store.connect(m.DB_PATH)
    entries = {}
    for bssid in ('02:10:00:00:00:01', '02:10:00:00:00:02'):
        found = mynets.baseline_from_db(conn, bssid)
        if found:
            entries[bssid] = mynets.make_entry(bssid, found)
    conn.close()
    mynets.save(m._mynets_path(), entries)
    # Last 10 minutes, with a few incidents for the Detection tab
    build_capture(pcap, now - 600, now, attacks=True)
    subprocess.run([sys.executable, m.ENGINE, '--pcap', pcap, '--db', m.DB_PATH], check=True,
                   stdout=subprocess.DEVNULL)
    settings = json.loads(json.dumps(m.DEFAULT_SETTINGS))
    settings['radios'] = [
        {'iface': 'wlan1mon', 'enabled': True, 'hopping': True, 'channels': [1, 6, 11, 2, 7, 3, 8, 4, 9, 5, 10]},
        {'iface': 'wlan3mon', 'enabled': True, 'hopping': True,
         'channels': [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128, 132, 136,
                      140, 144, 149, 153, 157, 161, 165]},
    ]
    m._save_settings(settings)
    radios = test_module.FakeRadios()
    radios.add('wlan1mon', 'phy1', mode='monitor')
    # SENTINEL_DEMO_ADAPTER=none: no 5 GHz adapter; =wlan4: the adapter under another name
    adapter = os.environ.get('SENTINEL_DEMO_ADAPTER', 'wlan3')
    if adapter != 'none':
        radios.add(adapter, 'phy3', mode='managed', up=False)
        radios.add(adapter + 'mon', 'phy3', mode='monitor')
    if adapter != 'wlan3':
        settings['radios'][1].update(iface='' if adapter == 'none' else adapter + 'mon',
                                     enabled=adapter != 'none')
        m._save_settings(settings)
    def interfaces():
        out = radios.wireless_interfaces()
        for i in out:
            i['bands'] = ['2.4'] if i['phy'] == 'phy1' else ['2.4', '5']
        return out
    m._wireless_interfaces = interfaces
    m._run = radios.run
    m._sqlite_available = lambda: True
    # SENTINEL_DEMO_DEPENDENCY=missing|installing|failed shows the dependency notice
    state = os.environ.get('SENTINEL_DEMO_DEPENDENCY')
    if state:
        m._sqlite_available = lambda: False
        m._dep.update(state=None if state == 'missing' else state, job_id='demo',
                      error='wget returned 4: the Pineapple has no Internet access' if state == 'failed' else None)
    m._is_engine = lambda pid: True
    # Never signal a real process: the demo engine (PID 4242) does not exist, and saving
    # settings or clearing data would otherwise send SIGTERM/SIGKILL to that PID here.
    m._stop_engine = lambda: True
    m._start_engine = lambda: (True, 'Monitoring is starting')


RUNNING = {'on': True}


def engine_status():
    """A live-looking engine status, refreshed on every request."""
    now = time.time()
    chans5 = [36, 44, 64, 112, 149]
    return {'running': True, 'pid': 4242, 'started_at': now - 1260, 'heartbeat': now,
            'frames_per_sec': 142.6, 'frames_parsed': 183402, 'frames_rejected': 0, 'last_error': None,
            'radios': [
                {'iface': 'wlan1mon', 'hopping': True, 'current_channel': [1, 6, 11][int(now) % 3],
                 'channels': [1, 6, 11, 2, 7, 3, 8, 4, 9, 5, 10], 'unusable_channels': [], 'frames': 151220, 'error': None},
                {'iface': os.environ.get('SENTINEL_DEMO_ADAPTER', 'wlan3') + 'mon', 'hopping': True, 'current_channel': chans5[int(now) % 5],
                 'channels': [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128, 132,
                              136, 140, 144, 149, 153, 157, 161, 165],
                 'unusable_channels': [120, 124, 128], 'frames': 32182, 'error': None}][:1 if os.environ.get('SENTINEL_DEMO_ADAPTER') == 'none' else 2]}


def refresh_status():
    if not RUNNING['on']:
        m._engine_pid = lambda: None
        return
    m._engine_pid = lambda: 4242
    with open(m.PID_PATH, 'w') as fh:
        fh.write('4242')
    import store  # the engine's store: recreates the schema after "Clear collected data"
    conn = store.connect(m.DB_PATH)
    with conn:
        conn.execute('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)',
                     ('engine', json.dumps(engine_status())))
    conn.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
        action = body.get('action')
        if action == 'start_engine':
            RUNNING['on'] = True
            result = ('Monitoring is starting', True)
        elif action == 'stop_engine':
            RUNNING['on'] = False
            result = 'Monitoring stopped'
        else:
            refresh_status()
            handler = m.module.handlers.get(action)
            result = handler(types.SimpleNamespace(**body)) if handler else ('Unknown action', False)
        refresh_status()
        # SENTINEL_DEMO_CLOCK_BEHIND=<seconds>: a Pineapple whose clock is behind
        behind = float(os.environ.get('SENTINEL_DEMO_CLOCK_BEHIND') or 0)
        if behind and action == 'get_status' and isinstance(result, dict):
            result['server_time'] -= behind
        if isinstance(result, tuple):
            data, ok = result
            reply = {'payload': data} if ok else {'error': data}
        else:
            reply = {'payload': result}
        out = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(out)))
        self.end_headers()
        self.wfile.write(out)


if __name__ == '__main__':
    prepare(tempfile.mkdtemp(prefix='sentinel-demo-'))
    refresh_status()
    print('Demo API on http://127.0.0.1:8765 (Ctrl+C to stop)')
    HTTPServer(('127.0.0.1', 8765), Handler).serve_forever()
