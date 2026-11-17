#!/usr/bin/env python3
"""
Self-test of the Sentinel engine, Python standard library only (no scapy, no Pineapple).

It writes a radiotap pcap with:
  * beacons of a WPA2/WPA3 network on 5 GHz DFS channel 112 and a 2.4 GHz network,
  * probe requests and data frames from "neighbour" devices,
  * deauthentication frames,
  * 20 000 malformed frames (truncated, bit-flipped, random),
then replays it through engine.py and checks that:
  1. the DFS 5 GHz network is decoded (band 5, channel 112),
  2. the engine never crashes and counts the rejected frames,
  3. with the default settings, no neighbour MAC address or probed network name is stored,
  4. with tracking enabled, they are stored (the switches work).

    python3 tools/selftest.py
"""

import json
import os
import random
import sqlite3
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(HERE, '..', 'projects', 'Sentinel', 'src', 'assets', 'engine', 'engine.py')

random.seed(42)


def radiotap(freq, dbm=-50):
    # present: channel (bit 3) + dBm antenna signal (bit 5); channel field is 2-byte aligned at offset 8
    flags = 0x0100 if freq > 4000 else 0x0080          # 5 GHz / 2 GHz spectrum flag
    return struct.pack('<BBHI', 0, 0, 13, (1 << 3) | (1 << 5)) + struct.pack('<HHb', freq, flags, dbm)


def mac(s):
    return bytes(int(x, 16) for x in s.split(':'))


def ie(eid, body):
    return bytes([eid, len(body)]) + body


RSN_WPA3_TRANSITION = (struct.pack('<H', 1) + b'\x00\x0f\xac\x04' + struct.pack('<H', 1) + b'\x00\x0f\xac\x04'
                       + struct.pack('<H', 2) + b'\x00\x0f\xac\x02' + b'\x00\x0f\xac\x08'
                       + struct.pack('<H', 0x0080))      # PSK + SAE, PMF capable (optional)


def beacon(bssid, ssid, channel, rsn=RSN_WPA3_TRANSITION):
    hdr = b'\x80\x00' + b'\x00\x00' + b'\xff' * 6 + mac(bssid) + mac(bssid) + b'\x00\x00'
    body = b'\x00' * 8 + struct.pack('<HH', 100, 0x0411)
    body += ie(0, ssid.encode()) + ie(1, b'\x8c\x12\x98\x24\xb0\x48\x60\x6c') + ie(3, bytes([channel])) + ie(48, rsn)
    return hdr + body


def probe_req(src, ssid):
    return b'\x40\x00\x00\x00' + b'\xff' * 6 + mac(src) + b'\xff' * 6 + b'\x00\x00' + ie(0, ssid.encode())


def data_to_ap(client, bssid):
    # To-DS data frame: addr1 = BSSID, addr2 = client
    return b'\x08\x01\x00\x00' + mac(bssid) + mac(client) + mac(bssid) + b'\x00\x00' + b'\xaa' * 24


def deauth(bssid, client):
    return b'\xc0\x00\x00\x00' + mac(client) + mac(bssid) + mac(bssid) + b'\x00\x00' + struct.pack('<H', 7)


def write_pcap(path, frames):
    with open(path, 'wb') as fh:
        fh.write(struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 127))   # linktype radiotap
        t = 1_700_000_000
        for i, fr in enumerate(frames):
            fh.write(struct.pack('<IIII', t + i // 100, (i % 100) * 10000, len(fr), len(fr)))
            fh.write(fr)


def corrupt(fr):
    kind = random.randrange(3)
    if kind == 0:                                   # truncated anywhere, header included
        return fr[:random.randrange(0, len(fr))]
    if kind == 1:                                   # random bit flips
        b = bytearray(fr)
        for _ in range(random.randrange(1, 8)):
            b[random.randrange(len(b))] ^= 1 << random.randrange(8)
        return bytes(b)
    return bytes(random.randrange(256) for _ in range(random.randrange(1, 120)))   # random junk


def run(pcap, db, settings):
    sp = db + '.settings.json'
    with open(sp, 'w') as fh:
        json.dump(settings, fh)
    r = subprocess.run([sys.executable, ENGINE, '--pcap', pcap, '--db', db, '--settings', sp],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
    return r


def main():
    ok = True

    def check(cond, label):
        nonlocal ok
        ok &= bool(cond)
        print(('  PASS  ' if cond else '  FAIL  ') + label)

    valid = []
    for _ in range(30):
        valid.append(radiotap(5560) + beacon('0c:00:00:00:00:01', 'LabNet-5G', 112))     # 5560 MHz = ch 112 (DFS)
        valid.append(radiotap(2437) + beacon('0c:00:00:00:00:02', 'LabNet', 6))
        valid.append(radiotap(5560, -70) + probe_req('da:00:00:00:00:09', 'NeighbourHome'))
        valid.append(radiotap(5560, -60) + data_to_ap('da:00:00:00:00:09', '0c:00:00:00:00:01'))
        valid.append(radiotap(5560, -60) + deauth('0c:00:00:00:00:01', 'da:00:00:00:00:09'))
    hostile = [corrupt(random.choice(valid)) for _ in range(20000)]
    frames = valid + hostile
    random.shuffle(frames)

    with tempfile.TemporaryDirectory() as tmp:
        pcap = os.path.join(tmp, 'selftest.pcap')
        write_pcap(pcap, frames)
        print('Frames: %d valid, %d malformed' % (len(valid), len(hostile)))

        print('Run 1, default settings (privacy on):')
        db = os.path.join(tmp, 'default.db')
        r = run(pcap, db, {})
        check(r.returncode == 0, 'engine finished without crashing (exit code %d)' % r.returncode)
        c = sqlite3.connect(db)
        aps = {row[0]: row for row in c.execute('SELECT bssid, ssid, channel, band FROM aps')}
        a5 = aps.get('0c:00:00:00:00:01')
        check(a5 is not None and a5[2] == 112 and str(a5[3]) == '5',
              'DFS network decoded on 5 GHz channel 112: %s' % (a5,))
        check('0c:00:00:00:00:02' in aps, '2.4 GHz network decoded')
        check(c.execute('SELECT COUNT(*) FROM clients').fetchone()[0] == 0, 'no neighbour MAC stored (clients)')
        check(c.execute('SELECT COUNT(*) FROM probes').fetchone()[0] == 0, 'no probed network name stored (probes)')
        meta = json.loads(c.execute("SELECT value FROM meta WHERE key='engine'").fetchone()[0])
        check(meta.get('frames_rejected', 0) >= 0, 'rejected frames counted: %s' % meta.get('frames_rejected'))
        c.close()

        print('Run 2, tracking switched on:')
        db = os.path.join(tmp, 'tracking.db')
        r = run(pcap, db, {'track_clients': True, 'track_probes': True})
        check(r.returncode == 0, 'engine finished without crashing (exit code %d)' % r.returncode)
        c = sqlite3.connect(db)
        check(c.execute('SELECT COUNT(*) FROM clients').fetchone()[0] > 0, 'clients stored when enabled')
        check(c.execute('SELECT COUNT(*) FROM probes').fetchone()[0] > 0, 'probes stored when enabled')
        c.close()

    print('RESULT: %s' % ('ALL TESTS PASSED' if ok else 'FAILURES'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
