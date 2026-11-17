#!/usr/bin/env python3
"""
Generate a synthetic radiotap pcap to test the Sentinel engine without a
Pineapple. Requires scapy (pip install scapy) on your computer only; the
engine itself never needs it.

    python3 make_test_pcap.py test.pcap
    python3 ../projects/Sentinel/src/assets/engine/engine.py --pcap test.pcap --db test.db
"""

import random
import struct
import sys

from scapy.all import (RadioTap, Dot11, Dot11Beacon, Dot11Elt, Dot11ProbeReq,
                       Dot11ProbeResp, Dot11Deauth, Dot11Disas, PcapWriter, Raw, raw)

random.seed(7)

AKM = {'PSK': 2, '8021X': 1, 'SAE': 8, 'OWE': 18, '8021X-SHA256': 5}
CIPHER = {'TKIP': 2, 'CCMP': 4}


def rsn_ie(akms, pairwise=('CCMP',), group='CCMP', mfpc=False, mfpr=False):
    body = struct.pack('<H', 1)
    body += b'\x00\x0f\xac' + bytes([CIPHER[group]])
    body += struct.pack('<H', len(pairwise)) + b''.join(
        b'\x00\x0f\xac' + bytes([CIPHER[c]]) for c in pairwise)
    body += struct.pack('<H', len(akms)) + b''.join(
        b'\x00\x0f\xac' + bytes([AKM[a]]) for a in akms)
    caps = (0x80 if mfpc else 0) | (0x40 if mfpr else 0)
    body += struct.pack('<H', caps)
    return Dot11Elt(ID=48, info=body)


def wpa1_ie():
    body = b'\x00\x50\xf2\x01' + struct.pack('<H', 1) + b'\x00\x50\xf2\x02'
    body += struct.pack('<H', 1) + b'\x00\x50\xf2\x02'
    body += struct.pack('<H', 1) + b'\x00\x50\xf2\x02'
    return Dot11Elt(ID=221, info=body)


WPS_IE = Dot11Elt(ID=221, info=b'\x00\x50\xf2\x04\x10\x4a\x00\x01\x10')
HT_IE = Dot11Elt(ID=45, info=b'\x00' * 26)
VHT_IE = Dot11Elt(ID=191, info=b'\x00' * 12)


def chan_to_freq(ch):
    return 2407 + ch * 5 if ch <= 13 else 5000 + ch * 5


def rt(ch, rssi, fcs=False):
    return RadioTap(present='Flags+Channel+dBm_AntSignal', ChannelFrequency=chan_to_freq(ch),
                    ChannelFlags=0x00a0 if ch <= 13 else 0x0140, dBm_AntSignal=rssi,
                    Flags='FCS' if fcs else 0)


NETWORKS = [
    # bssid, ssid, channel, rssi, cap privacy, extra IEs
    ('02:aa:00:00:00:01', 'MaMaison', 6, -45, True, [rsn_ie(['PSK'])]),
    ('02:aa:00:00:00:02', 'Bureau', 36, -60, True, [rsn_ie(['SAE'], mfpc=True, mfpr=True), VHT_IE]),
    ('02:aa:00:00:00:03', 'Cafe-Gratuit', 1, -70, False, []),
    ('02:aa:00:00:00:04', 'VieuxRouteur', 11, -80, True, []),
    ('02:aa:00:00:00:05', 'Voisin', 6, -55, True,
     [rsn_ie(['PSK'], pairwise=('TKIP', 'CCMP'), group='TKIP'), wpa1_ie(), WPS_IE]),
    ('02:aa:00:00:00:06', 'Transition', 11, -65, True, [rsn_ie(['PSK', 'SAE'], mfpc=True)]),
    ('02:aa:00:00:00:07', 'Entreprise', 149, -72, True,
     [rsn_ie(['8021X'], mfpc=True, mfpr=True), VHT_IE]),
    ('02:aa:00:00:00:08', '', 1, -50, True, [rsn_ie(['PSK'], mfpc=True)]),          # hidden
    ('02:aa:00:00:00:09', 'Enhanced-Open', 44, -58, True, [rsn_ie(['OWE'], mfpc=True, mfpr=True)]),
]


def ext_radiotap(ch, rssi, fcs=False):
    """
    Hand-built radiotap header with two presence words, as sent by Mediatek
    drivers: namespace 1 = Flags, Channel, dBm signal; namespace 2 = per-antenna
    signal. Scapy does not build this layout correctly, hence the raw bytes.
    """
    word1 = (1 << 1) | (1 << 3) | (1 << 5) | (1 << 29) | (1 << 31)
    word2 = (1 << 5)
    body = struct.pack('<B', 0x10 if fcs else 0)            # Flags @12
    body += b'\x00'                                          # pad to 14
    body += struct.pack('<HH', chan_to_freq(ch), 0x00a0 if ch <= 13 else 0x0140)
    body += struct.pack('<b', rssi)                          # dBm signal @18
    body += struct.pack('<b', rssi - 2)                      # antenna 0 signal (ns 2)
    hdr_len = 8 + 4 + len(body)
    return struct.pack('<BBHII', 0, 0, hdr_len, word1, word2) + body


def beacon(bssid, ssid, ch, rssi, privacy, extra, fcs=False, ext=False):
    cap = 'ESS+privacy' if privacy else 'ESS'
    rssi = rssi + random.randint(-3, 3)
    pkt = (rt(ch, rssi, fcs) /
           Dot11(type=0, subtype=8, addr1='ff:ff:ff:ff:ff:ff', addr2=bssid, addr3=bssid) /
           Dot11Beacon(cap=cap, beacon_interval=100) /
           Dot11Elt(ID=0, info=ssid.encode()) /
           Dot11Elt(ID=1, info=b'\x82\x84\x8b\x96\x0c\x12\x18\x24') /
           Dot11Elt(ID=3, info=bytes([ch])) / HT_IE)
    for ie in extra:
        pkt = pkt / ie
    if fcs:
        pkt = pkt / Raw(b'\xde\xad\xbe\xef')  # fake FCS, must be stripped by the parser
    if ext:
        return ext_radiotap(ch, rssi, fcs) + raw(pkt[Dot11])
    return pkt


def main(path):
    w = PcapWriter(path, linktype=127, sync=True)
    t = 1_700_000_000.0
    frames = 0
    for i in range(30):  # 30 rounds of beacons
        for n, net in enumerate(NETWORKS):
            pkt = beacon(*net, fcs=(n % 3 == 0), ext=(n % 4 == 1))
            if isinstance(pkt, bytes):
                w._write_packet(pkt, linktype=127, sec=int(t), usec=int((t % 1) * 1e6))
            else:
                pkt.time = t
                w.write(pkt)
            t += 0.01
            frames += 1

    # Probe response revealing the hidden SSID
    pr = (rt(1, -50) / Dot11(type=0, subtype=5, addr1='02:cc:00:00:00:01',
                              addr2='02:aa:00:00:00:08', addr3='02:aa:00:00:00:08') /
          Dot11ProbeResp(cap='ESS+privacy', beacon_interval=100) /
          Dot11Elt(ID=0, info=b'ReseauCache') / Dot11Elt(ID=3, info=b'\x01') /
          rsn_ie(['PSK'], mfpc=True))
    pr.time = t
    w.write(pr)

    # Probe requests (client remembering networks)
    for ssid in ['MaMaison', 'Aeroport-WiFi', 'Hotel-Paris', '']:
        p = (rt(6, -40) / Dot11(type=0, subtype=4, addr1='ff:ff:ff:ff:ff:ff',
                                 addr2='a4:83:e7:11:22:33', addr3='ff:ff:ff:ff:ff:ff') /
             Dot11ProbeReq() / Dot11Elt(ID=0, info=ssid.encode()))
        p.time = t
        w.write(p)
        t += 0.01

    # Data frames: two clients on MaMaison (one with a randomized MAC)
    for client in ['a4:83:e7:11:22:33', '7a:11:22:33:44:55']:
        for _ in range(5):
            d = (rt(6, -42) / Dot11(type=2, subtype=0, FCfield=0x01,
                                     addr1='02:aa:00:00:00:01', addr2=client,
                                     addr3='02:aa:00:00:00:01') / Raw(b'\x00' * 40))
            d.time = t
            w.write(d)
            t += 0.01

    # Deauth burst against MaMaison (spoofed from the AP)
    for _ in range(120):
        d = (rt(6, -30) / Dot11(type=0, subtype=12, addr1='a4:83:e7:11:22:33',
                                 addr2='02:aa:00:00:00:01', addr3='02:aa:00:00:00:01') /
             Dot11Deauth(reason=7))
        d.time = t
        w.write(d)
        t += 0.005
    d = (rt(6, -30) / Dot11(type=0, subtype=10, addr1='ff:ff:ff:ff:ff:ff',
                             addr2='02:aa:00:00:00:01', addr3='02:aa:00:00:00:01') /
         Dot11Disas(reason=8))
    d.time = t
    w.write(d)

    # Garbage that must not crash the parser
    for junk in [b'', b'\x00', b'\x00\x00\xff\xff', b'\x00\x00\x08\x00\x00\x00\x00\x00\x80',
                 bytes(random.getrandbits(8) for _ in range(60))]:
        w._write_packet(junk, linktype=127, sec=int(t), usec=0)
    w.close()
    print('wrote %s (%d beacons)' % (path, frames))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'test.pcap')
