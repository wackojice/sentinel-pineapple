#!/usr/bin/env python3
"""
Regression tests for the Sentinel engine. They run on any computer, no
Pineapple needed:

    pip install scapy
    python3 tools/test_engine.py
"""

import os
import random
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'projects', 'Sentinel', 'src', 'assets', 'engine'))
sys.path.insert(0, HERE)

import analysis  # noqa: E402
import dot11  # noqa: E402
import engine  # noqa: E402
import nl80211  # noqa: E402
import store  # noqa: E402
import make_test_pcap as gen  # noqa: E402

from scapy.all import Dot11, Dot11Beacon, Dot11Deauth, Dot11Elt, RadioTap, raw  # noqa: E402


def beacon_heard_on(tuned, advertised, ie=3):
    """A beacon from an AP on `advertised`, captured while tuned to `tuned`."""
    body = bytes([advertised]) + (b'\x00' * 21 if ie == 61 else b'')
    return raw(RadioTap(present='Flags+Channel+dBm_AntSignal',
                        ChannelFrequency=gen.chan_to_freq(tuned), ChannelFlags=0x00a0,
                        dBm_AntSignal=-50, Flags=0) /
               Dot11(type=0, subtype=8, addr1='ff:ff:ff:ff:ff:ff',
                     addr2='02:00:00:00:00:01', addr3='02:00:00:00:00:01') /
               Dot11Beacon(cap='ESS+privacy') / Dot11Elt(ID=0, info=b'Home') /
               Dot11Elt(ID=ie, info=body) / gen.rsn_ie(['PSK']))


class EngineTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.engine = engine.Engine(os.path.join(self.dir, 'test.db'))
        self.conn = self.engine.conn

    def replay_sample(self):
        pcap = os.path.join(self.dir, 'sample.pcap')
        gen.main(pcap)
        self.engine.run_pcap(pcap)
        return dict((r['ssid'], dict(r)) for r in self.conn.execute('SELECT * FROM aps'))

    def test_security_is_classified(self):
        aps = self.replay_sample()
        expected = {
            'MaMaison': ('WPA2-PSK', 'none'), 'Bureau': ('WPA3-SAE', 'required'),
            'Cafe-Gratuit': ('Open', 'none'), 'VieuxRouteur': ('WEP', 'none'),
            'Voisin': ('WPA/WPA2-PSK', 'none'), 'Transition': ('WPA3-Transition', 'capable'),
            'Entreprise': ('WPA2-Enterprise', 'required'), 'Enhanced-Open': ('OWE', 'required'),
        }
        for ssid, (security, pmf) in expected.items():
            self.assertEqual((aps[ssid]['security'], aps[ssid]['pmf']), (security, pmf), ssid)
        self.assertEqual(aps['Voisin']['wps'], 1)

    def test_hidden_ssid_is_revealed_by_probe_response(self):
        aps = self.replay_sample()
        self.assertEqual(aps['ReseauCache']['hidden'], 1)

    def test_privacy_defaults_store_no_clients_or_probes(self):
        self.replay_sample()
        one = lambda sql: self.conn.execute(sql).fetchone()[0]  # noqa: E731
        self.assertEqual(one('SELECT COUNT(*) FROM clients'), 0)
        self.assertEqual(one('SELECT COUNT(*) FROM probes'), 0)
        self.assertEqual(one('SELECT SUM(count) FROM disconnections'), 121)

    def test_clients_probes_and_deauths_are_recorded(self):
        self.engine = engine.Engine(os.path.join(self.dir, 'tracking.db'),
                                    track_clients=True, track_probes=True)
        self.conn = self.engine.conn
        self.replay_sample()
        one = lambda sql: self.conn.execute(sql).fetchone()[0]  # noqa: E731
        self.assertEqual(one('SELECT COUNT(*) FROM clients'), 2)
        self.assertEqual(one('SELECT COUNT(*) FROM clients WHERE randomized = 1'), 1)
        self.assertEqual(one('SELECT COUNT(*) FROM probes'), 3)  # wildcard probe ignored
        self.assertEqual(one('SELECT SUM(count) FROM disconnections'), 121)

    def test_audit_grades(self):
        self.replay_sample()
        audit = analysis.security_audit(self.conn, now=1700000010)
        grades = dict((n['ssid'], n['grade']) for n in audit['networks'])
        self.assertEqual(grades['Cafe-Gratuit'], 'critical')
        self.assertEqual(grades['VieuxRouteur'], 'critical')
        self.assertEqual(grades['Voisin'], 'high')
        self.assertEqual(grades['MaMaison'], 'medium')
        self.assertEqual(grades['Bureau'], 'good')

    def test_ap_channel_does_not_drift_when_heard_on_neighbouring_channels(self):
        for tuned in (6, 5, 7, 4):
            self.engine.handle(beacon_heard_on(tuned, 6), time.time())
            self.engine.agg.flush()
            self.assertEqual(self.conn.execute('SELECT channel FROM aps').fetchone()[0], 6)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM ap_channels').fetchone()[0], 1)

    def test_ap_channel_from_ht_operation(self):
        self.engine.handle(beacon_heard_on(5, 6, ie=61), time.time())
        self.engine.agg.flush()
        self.assertEqual(self.conn.execute('SELECT channel FROM aps').fetchone()[0], 6)

    def test_advertised_channel_from_another_band_is_ignored(self):
        self.engine.handle(beacon_heard_on(6, 149), time.time())
        self.engine.agg.flush()
        self.assertEqual(self.conn.execute('SELECT channel FROM aps').fetchone()[0], 6)

    def test_data_traffic_counted_with_privacy_defaults(self):
        # Tracking off (default): data frames must still count as channel traffic,
        # but no client may be stored. FCfield 0x01 = to-DS.
        data = raw(RadioTap(present='Flags+Channel+dBm_AntSignal',
                            ChannelFrequency=gen.chan_to_freq(11), ChannelFlags=0x00a0,
                            dBm_AntSignal=-55, Flags=0) /
                   Dot11(type=2, subtype=0, FCfield=0x01, addr1='02:00:00:00:00:01',
                         addr2='da:00:00:00:00:09', addr3='02:00:00:00:00:01') / (b'\xaa' * 24))
        ts = time.time()
        for _ in range(500):
            self.engine.handle(data, ts)
        self.engine.agg.flush()
        one = lambda sql: self.conn.execute(sql).fetchone()[0]  # noqa: E731
        self.assertEqual(one('SELECT SUM(data) FROM channel_stats WHERE channel = 11'), 500)
        self.assertEqual(one('SELECT COUNT(*) FROM clients'), 0)

    def test_deauth_counts_without_device_addresses_by_default(self):
        # Audit 5.2: with tracking off, deauth records must not keep device MAC addresses
        self.replay_sample()
        one = lambda sql: self.conn.execute(sql).fetchone()[0]  # noqa: E731
        self.assertEqual(one('SELECT SUM(count) FROM disconnections'), 121)
        self.assertEqual(one("SELECT COUNT(*) FROM disconnections WHERE src != '' OR dst != ''"), 0)

    def test_deauth_addresses_kept_when_tracking_is_on(self):
        self.engine = engine.Engine(os.path.join(self.dir, 'tracking.db'), track_clients=True)
        self.conn = self.engine.conn
        self.replay_sample()
        self.assertGreater(self.conn.execute(
            "SELECT COUNT(*) FROM disconnections WHERE dst != ''").fetchone()[0], 0)

    def test_beacon_flood_with_random_bssids_is_capped(self):
        # Audit 5.1: a flood of beacons with random BSSIDs must not fill the flash
        old = (store.MAX_APS, store.MAX_NEW_PER_FLUSH)
        store.MAX_APS, store.MAX_NEW_PER_FLUSH = 50, 20
        try:
            self.engine.handle(beacon_heard_on(6, 6), time.time())  # a real AP, known first
            self.engine.agg.flush()
            for n in range(300):
                bssid = '06:%02x:%02x:00:00:01' % (n // 256, n % 256)
                self.engine.handle(raw(RadioTap(present='Flags+Channel+dBm_AntSignal',
                                                ChannelFrequency=gen.chan_to_freq(6), ChannelFlags=0x00a0,
                                                dBm_AntSignal=-60, Flags=0) /
                                       Dot11(type=0, subtype=8, addr1='ff:ff:ff:ff:ff:ff', addr2=bssid, addr3=bssid) /
                                       Dot11Beacon(cap='ESS') / Dot11Elt(ID=0, info=b'flood')), time.time())
                if n % 30 == 29:
                    self.engine.agg.flush()
            self.engine.agg.flush()
            one = lambda sql: self.conn.execute(sql).fetchone()[0]  # noqa: E731
            self.assertEqual(one('SELECT COUNT(*) FROM aps'), 50)
            self.assertGreater(self.engine.agg.dropped, 0)
            # The access point that was known before the flood is still updated
            before = one("SELECT beacons FROM aps WHERE bssid = '02:00:00:00:00:01'")
            self.engine.handle(beacon_heard_on(6, 6), time.time())
            self.engine.agg.flush()
            self.assertEqual(one("SELECT beacons FROM aps WHERE bssid = '02:00:00:00:00:01'"), before + 1)
        finally:
            store.MAX_APS, store.MAX_NEW_PER_FLUSH = old

    def test_ssid_cleaning(self):
        # Audit 7.1: control, format and separator characters must not reach the display
        self.assertEqual(dot11.clean_ssid('Home\nNet'), 'Home\u00b7Net')
        self.assertEqual(dot11.clean_ssid('abc\u202edef'), 'abc\u00b7def')       # right-to-left override
        self.assertEqual(dot11.clean_ssid('a\u2028b\u2029c'), 'a\u00b7b\u00b7c')
        self.assertEqual(dot11.clean_ssid('Café-du-Coin'), 'Café-du-Coin')
        self.assertLessEqual(len(dot11.clean_ssid('é' * 40).encode('utf-8')), 32)
        self.assertEqual(dot11.clean_ssid(''), '')

    def test_local_interface_addresses_are_read(self):
        # Audit 6.5: the Pineapple's own access points must be known to the engine
        sysfs = os.path.join(self.dir, 'net')
        for name, mac in (('wlan0', '00:13:37:AA:BB:CC'), ('lo', '00:00:00:00:00:00'), ('br-lan', '02:13:37:aa:bb:cc')):
            os.makedirs(os.path.join(sysfs, name))
            with open(os.path.join(sysfs, name, 'address'), 'w') as fh:
                fh.write(mac + '\n')
        self.assertEqual(engine.read_local_macs(sysfs), {'00:13:37:aa:bb:cc', '02:13:37:aa:bb:cc'})
        self.assertEqual(engine.read_local_macs(os.path.join(self.dir, 'missing')), set())

    def test_list_aps_is_limited(self):
        self.replay_sample()
        self.assertEqual(len(analysis.list_aps(self.conn, max_age=10 ** 10, limit=3)), 3)

    def test_broadcast_deauths_are_counted_per_access_point(self):
        frame = raw(RadioTap(present='Flags+Channel+dBm_AntSignal', ChannelFrequency=gen.chan_to_freq(6),
                             ChannelFlags=0x00a0, dBm_AntSignal=-50, Flags=0) /
                    Dot11(type=0, subtype=12, addr1='ff:ff:ff:ff:ff:ff', addr2='02:00:00:00:00:07',
                          addr3='02:00:00:00:00:07') / Dot11Deauth(reason=7))
        for _ in range(4):
            self.engine.handle(frame, time.time())
        self.assertEqual(self.engine.agg.disc_broadcast, {'02:00:00:00:00:07': 4})

    def test_my_networks_get_their_own_score(self):
        # Roadmap 4.7: marking networks adds a score, without changing the neighbourhood's
        self.replay_sample()
        plain = analysis.security_audit(self.conn, now=1700000010)
        mine = set(n['bssid'] for n in plain['networks'] if n['ssid'] in ('Bureau', 'MaMaison'))
        audit = analysis.security_audit(self.conn, now=1700000010, mine=mine)
        self.assertEqual((audit['score'], audit['summary']), (plain['score'], plain['summary']))
        self.assertEqual(audit['my_total'], 2)
        self.assertEqual(audit['my_score'], 50)  # Bureau good, MaMaison medium
        self.assertEqual(set(n['ssid'] for n in audit['networks'][:2]), {'Bureau', 'MaMaison'})
        self.assertTrue(all(n['mine'] == (n['bssid'] in mine) for n in audit['networks']))
        self.assertIsNone(plain['my_score'])
        arcs = analysis.spectrum(self.conn, max_age=10 ** 10, mine=mine)
        self.assertEqual(sum(1 for a in arcs if a['mine']), 2)

    def test_live_capture_runs_at_lower_priority(self):
        # Audit 4.1: the engine yields the single core to the web interface
        calls = []
        old = (engine.os.nice, engine.Engine.run_live, sys.argv)
        engine.os.nice = lambda n: calls.append(n)
        engine.Engine.run_live = lambda self: None
        sys.argv = ['engine.py', '--db', os.path.join(self.dir, 'live.db'), '--iface', 'wlan9mon']
        try:
            self.assertEqual(engine.main(), 0)
        finally:
            engine.os.nice, engine.Engine.run_live, sys.argv = old
        self.assertEqual(calls, [engine.NICENESS])
        self.assertGreater(engine.NICENESS, 0)

    def test_beacon_cache_reuses_identical_beacons_only(self):
        # 0.7: a beacon is decoded again only when its content changed (timestamp and TIM aside)
        dot11._beacon_cache.clear()
        dot11.cache_stats.update(hits=0, misses=0)

        def frame(tim=0, akms=('PSK',), ssid=b'Home', ts=0):
            return raw(RadioTap(present='Flags+Channel+dBm_AntSignal', ChannelFrequency=gen.chan_to_freq(6),
                                ChannelFlags=0x00a0, dBm_AntSignal=-50, Flags=0) /
                       Dot11(type=0, subtype=8, addr1='ff:ff:ff:ff:ff:ff', addr2='02:00:00:00:00:05',
                             addr3='02:00:00:00:00:05') /
                       Dot11Beacon(cap='ESS+privacy', timestamp=ts) / Dot11Elt(ID=0, info=ssid) /
                       Dot11Elt(ID=5, info=bytes([tim, 3, 0, 0])) / Dot11Elt(ID=3, info=b'\x06') /
                       gen.rsn_ie(list(akms)))
        first = dot11.parse_frame(frame())
        again = dot11.parse_frame(frame(tim=1, ts=123456))          # other timestamp and TIM: same beacon
        self.assertIs(again.info, first.info)
        self.assertEqual(dot11.cache_stats, {'hits': 1, 'misses': 1})
        changed = dot11.parse_frame(frame(akms=('SAE',)))           # security changed: decoded again
        self.assertEqual(changed.info['security'], 'WPA3-SAE')
        self.assertNotEqual(changed.info['security'], first.info['security'])
        renamed = dot11.parse_frame(frame(ssid=b'Other'))
        self.assertEqual(renamed.info['ssid'], 'Other')
        self.assertEqual(dot11.cache_stats['misses'], 3)

    def test_beacon_cache_is_bounded(self):
        dot11._beacon_cache.clear()
        old = dot11.BEACON_CACHE_MAX
        dot11.BEACON_CACHE_MAX = 10
        try:
            template = beacon_heard_on(6, 6)
            for i in range(25):  # 25 different BSSIDs
                dot11.parse_frame(template.replace(b'\x02\x00\x00\x00\x00\x01', bytes([2, 0, 0, 0, 0, i + 16])))
            self.assertLessEqual(len(dot11._beacon_cache), 10)
        finally:
            dot11.BEACON_CACHE_MAX = old

    def test_parser_survives_corrupted_frames(self):
        pcap = os.path.join(self.dir, 'sample.pcap')
        gen.main(pcap)
        frames = [data for _, data in engine.read_pcap(pcap)]
        rnd = random.Random(1)
        for _ in range(20000):
            frame = bytearray(rnd.choice(frames))
            for _ in range(rnd.randint(1, 6)):
                if frame:
                    frame[rnd.randrange(len(frame))] = rnd.getrandbits(8)
            if frame and rnd.random() < 0.3:
                frame = frame[:rnd.randrange(len(frame))]
            self.engine.handle(bytes(frame), time.time())  # must never raise
        self.engine.agg.flush()


class HopperTest(unittest.TestCase):

    def hop(self, answers, rounds):
        """Run the hopper loop `rounds` times with scripted `iw` results."""
        hopper = engine.ChannelHopper('wlanX', [1, 6, 11], dwell=0)
        calls = []

        def fake_set_channel(ch):
            calls.append(ch)
            if len(calls) >= rounds * 3:
                hopper.stop()
            return answers(ch, len(calls))
        hopper.set_channel = fake_set_channel
        hopper.run()
        return hopper, calls

    def test_one_failure_does_not_blacklist(self):
        hopper, _ = self.hop(lambda ch, n: not (ch == 6 and n == 2), rounds=2)
        self.assertEqual(hopper.bad, set())

    def test_repeated_failures_blacklist_then_retry(self):
        hopper, calls = self.hop(lambda ch, n: ch != 11, rounds=4)
        self.assertEqual(hopper.bad, {11})
        self.assertEqual(calls.count(11), engine.BAD_CHANNEL_FAILURES)
        hopper.retry_at = 0  # retry window elapsed
        hopper._halt.clear()
        calls_before = len(calls)
        hopper.set_channel = lambda ch: (calls.append(ch), hopper.stop())[0] is None
        hopper.run()
        self.assertEqual(hopper.bad, set())
        self.assertGreater(len(calls), calls_before)

    def test_radio_that_refuses_every_channel_reports_an_error_then_recovers(self):
        # Issue #5: on the MK7AC every channel change failed with "Resource busy" and
        # the 5 GHz radio stayed on one channel without saying anything.
        radio = engine.Radio('wlan3mon', [36, 40, 44], True, 0)
        hopper = radio.hopper = engine.ChannelHopper('wlan3mon', [36, 40, 44], dwell=0)
        hopper.set_channel = lambda ch: False

        def pause(seconds):
            if seconds == 5:  # the pause the hopper takes when no channel is usable
                hopper.stop()
        hopper._halt.wait = pause
        hopper.run()
        self.assertEqual(hopper.bad, {36, 40, 44})
        self.assertIn('wlan3mon cannot change channel', radio.status()['error'])

        # The radio is freed: at the next retry the channels work and the error goes away
        hopper._halt.clear()
        hopper.retry_at = 0
        hopper.set_channel = lambda ch: True
        hopper._halt.wait = lambda seconds: hopper.stop()
        hopper.run()
        self.assertEqual(hopper.bad, set())
        self.assertIsNone(radio.status()['error'])
        self.assertEqual(radio.status()['current_channel'], 36)



class Nl80211Test(unittest.TestCase):
    """0.7: channel changes through nl80211, with `iw` as the fallback."""

    def test_set_channel_message_matches_iw(self):
        import struct
        msg = nl80211.set_channel_message(family=39, ifindex=7, freq=5560, seq=5)
        length, mtype, flags, seq, pid = struct.unpack_from('=IHHII', msg)
        self.assertEqual((length, mtype, flags, seq, pid), (len(msg), 39, 0x5, 5, 0))
        self.assertEqual(struct.unpack_from('=BBH', msg, 16), (nl80211.NL80211_CMD_SET_WIPHY, 0, 0))
        attrs, off = {}, 20
        while off < len(msg):
            alen, atype = struct.unpack_from('=HH', msg, off)
            attrs[atype] = struct.unpack_from('=I', msg, off + 4)[0]
            off += (alen + 3) & ~3
        self.assertEqual(attrs, {nl80211.NL80211_ATTR_IFINDEX: 7, nl80211.NL80211_ATTR_WIPHY_FREQ: 5560,
                                 nl80211.NL80211_ATTR_WIPHY_CHANNEL_TYPE: nl80211.NL80211_CHAN_NO_HT})

    def test_channel_frequencies(self):
        self.assertEqual([nl80211.channel_freq(c) for c in (1, 6, 13, 14, 36, 112, 165, 0, 200)],
                         [2412, 2437, 2472, 2484, 5180, 5560, 5825, None, None])

    def test_kernel_answers_are_read(self):
        import struct

        def answer(seq, code):
            return struct.pack('=IHHII', 36, nl80211.NLMSG_ERROR, 0, seq, 0) + struct.pack('=i', code) + b'\x00' * 16
        self.assertEqual(nl80211.parse_ack(answer(3, 0), 3), 0)
        self.assertEqual(nl80211.parse_ack(answer(3, -16), 3), -16)       # EBUSY
        self.assertIsNone(nl80211.parse_ack(answer(2, 0), 3))             # someone else's answer
        self.assertIsNone(nl80211.parse_ack(b'\x00' * 8, 3))

    def hopper(self, nl_ok, iw_ok):
        h = engine.ChannelHopper('wlan3mon', [36], dwell=0)
        calls = []

        class FakeNl(object):
            def set_channel(self, iface, ch):
                calls.append('nl')
                return nl_ok

            def close(self):
                pass
        h.nl, h.method = FakeNl(), 'nl80211'
        h._iw = lambda ch: calls.append('iw') or iw_ok
        return h, calls

    def test_nl80211_used_when_it_works(self):
        h, calls = self.hopper(True, True)
        self.assertTrue(h.set_channel(36))
        self.assertTrue(h.set_channel(36))
        self.assertEqual((calls, h.method), (['nl', 'nl'], 'nl80211'))

    def test_falls_back_to_iw_for_good_when_only_iw_works(self):
        h, calls = self.hopper(False, True)
        self.assertTrue(h.set_channel(36))
        self.assertTrue(h.set_channel(36))
        self.assertEqual((calls, h.method), (['nl', 'iw', 'iw'], 'iw'))

    def test_channel_refused_by_both_stays_on_nl80211(self):
        h, calls = self.hopper(False, False)  # e.g. a weather radar channel
        self.assertFalse(h.set_channel(120))
        self.assertEqual(h.method, 'nl80211')

if __name__ == '__main__':
    unittest.main(verbosity=1)
