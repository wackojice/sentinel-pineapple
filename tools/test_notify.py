#!/usr/bin/env python3
"""
Sentinel - tests of the ntfy notifications (assets/engine/notify.py), against a local
stand-in for an ntfy server. Standard library only.

    python3 tools/test_notify.py
"""

import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'projects', 'Sentinel', 'src', 'assets', 'engine'))
import muted  # noqa: E402
import notify  # noqa: E402
import store  # noqa: E402


class FakeNtfy(object):
    """Records every POST; answers `status` (200 by default)."""

    def __init__(self):
        self.posts = []
        self.status = 200
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
                outer.posts.append({'path': self.path, 'headers': dict(self.headers), 'body': body.decode('utf-8')})
                self.send_response(outer.status)
                self.end_headers()
                self.wfile.write(b'{}')

            def log_message(self, *_):
                pass

        self.server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        self.url = 'http://127.0.0.1:%d' % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class NotifyTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, 'sentinel.db')
        self.path = os.path.join(self.dir, notify.FILENAME)
        self.ntfy = FakeNtfy()
        self.conn = store.connect(self.db)

    def tearDown(self):
        self.conn.close()
        self.ntfy.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def configure(self, **extra):
        cfg = dict(notify.DEFAULTS, enabled=True, server=self.ntfy.url, topic='sentinel-test')
        cfg.update(extra)
        notify.save(self.path, cfg)
        return cfg

    def alert(self, severity='high', kind='deauth_flood', title='Burst of 25 deauthentication frames on "Home"'):
        with self.conn:
            store.add_event(self.conn, 'wids', kind, severity, title, bssid='02:00:00:00:00:01')

    def notifier(self):
        return notify.Notifier(self.db, self.dir)

    # -- settings

    def test_validate(self):
        old = notify.load(self.path)
        good = {'enabled': True, 'server': 'https://ntfy.sh/', 'topic': 'sentinel-ab12', 'min_severity': 'high',
                'max_per_hour': 10, 'status_messages': True, 'token': 'tk_secret'}
        cfg, err = notify.validate(good, old)
        self.assertIsNone(err)
        self.assertEqual((cfg['server'], cfg['token']), ('https://ntfy.sh', 'tk_secret'))
        for bad in ({'enabled': 'yes'}, {'server': 'ftp://x'}, {'server': 'https://a b'}, {'topic': '../x'},
                    {'topic': ''}, {'min_severity': 'low'}, {'max_per_hour': 0}, {'max_per_hour': 61},
                    {'max_per_hour': True}, {'token': 'a b'}, {'status_messages': 1}):
            self.assertIsNotNone(notify.validate(dict(good, **bad), old)[1], bad)
        self.assertIsNotNone(notify.validate('nope', old)[1])
        kept, _ = notify.validate(dict(good, token=''), cfg)              # empty keeps the saved token
        self.assertEqual(kept['token'], 'tk_secret')
        cleared, _ = notify.validate(dict(good, token='', clear_token=True), cfg)
        self.assertEqual(cleared['token'], '')

    def test_saved_settings_are_private(self):
        cfg = self.configure(token='tk_secret')
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        shown = notify.public(cfg)
        self.assertNotIn('token', shown)
        self.assertTrue(shown['has_token'])
        self.assertNotIn('tk_secret', json.dumps(shown))
        with open(self.path, 'w') as fh:
            fh.write('{damaged')
        self.assertFalse(notify.load(self.path)['enabled'])                 # a damaged file sends nothing

    # -- sending

    def test_send(self):
        cfg = self.configure(token='tk_secret')
        err = notify.send(cfg, 'Sentinel: Critiqué', 'Line one\x07\nLine two \x1b[31m', priority=5, tags='warning')
        self.assertIsNone(err)
        post = self.ntfy.posts[0]
        self.assertEqual(post['path'], '/sentinel-test')
        self.assertEqual(post['headers']['Priority'], '5')
        self.assertEqual(post['headers']['Authorization'], 'Bearer tk_secret')
        self.assertTrue(post['headers']['Title'].startswith('Sentinel: Critiqu'))
        self.assertNotIn('\x07', post['body'])
        self.assertNotIn('\x1b', post['body'])
        self.assertIn('Line one\nLine two', post['body'])
        self.assertNotIn('Markdown', post['headers'])                       # never rendered as Markdown

    def test_send_errors_are_short_and_never_raise(self):
        cfg = self.configure()
        self.ntfy.status = 403
        self.assertIn('403', notify.send(cfg, 't', 'm'))
        self.assertIn('access token', notify.send(cfg, 't', 'm'))
        dead = dict(cfg, server='http://127.0.0.1:1')
        self.assertIn('Could not reach', notify.send(dead, 't', 'm', timeout=2))

    # -- the engine's sender

    def test_nothing_old_is_sent(self):
        self.alert()
        self.configure()
        n = self.notifier()
        self.assertEqual(n.run_once(self.conn, time.time()), 0)
        self.alert()
        self.assertEqual(n.run_once(self.conn, time.time()), 1)
        self.assertIn('Burst of 25', self.ntfy.posts[0]['body'])
        self.assertEqual(self.ntfy.posts[0]['headers']['Priority'], '4')

    def test_severity_and_muted_types(self):
        self.configure(min_severity='high')
        n = self.notifier()
        n.run_once(self.conn, time.time())
        self.alert(severity='medium', kind='my_ap_changed')
        self.alert(severity='info', kind='my_ap_channel')
        self.alert(severity='critical', kind='evil_twin', title='Another access point is using your network name "Home"')
        muted.save(os.path.join(self.dir, muted.FILENAME), ['deauth_flood'])
        self.alert(severity='high', kind='deauth_flood')
        self.assertEqual(n.run_once(self.conn, time.time()), 1)
        self.assertIn('Another access point', self.ntfy.posts[0]['body'])
        self.assertEqual(self.ntfy.posts[0]['headers']['Priority'], '5')

    def test_hourly_limit_then_one_summary(self):
        self.configure(max_per_hour=3)
        n = self.notifier()
        now = time.time()
        n.run_once(self.conn, now)
        for _ in range(7):
            self.alert()
        self.assertEqual(n.run_once(self.conn, now), 3)
        self.assertEqual(n.held, 4)
        self.assertEqual(n.run_once(self.conn, now + 3700), 1)               # an hour later: one summary
        self.assertIn('4 more alerts were not sent', self.ntfy.posts[-1]['body'])
        self.assertEqual(n.held, 0)

    def test_a_failed_send_is_tried_again(self):
        self.configure()
        n = self.notifier()
        n.run_once(self.conn, time.time())
        self.alert()
        self.ntfy.status = 500
        self.assertEqual(n.run_once(self.conn, time.time()), 0)
        self.assertIn('500', n.last_error)
        self.ntfy.status = 200
        self.assertEqual(n.run_once(self.conn, time.time()), 1)
        self.assertIsNone(n.last_error)

    def test_status_messages(self):
        self.configure()
        n = self.notifier()
        n.run_once(self.conn, time.time())
        n.status('wlan3mon stopped working (Network is down).')
        self.assertEqual(n.run_once(self.conn, time.time()), 1)
        self.assertIn('wlan3mon stopped working', self.ntfy.posts[0]['body'])
        self.configure(status_messages=False)
        n.status('Sentinel stopped listening.')
        self.assertEqual(n.run_once(self.conn, time.time()), 0)

    def test_turned_off_sends_nothing_and_keeps_up(self):
        self.configure(enabled=False)
        n = self.notifier()
        self.alert()
        n.status('Sentinel stopped listening.')
        self.assertEqual(n.run_once(self.conn, time.time()), 0)
        self.configure()                                                     # turned on later
        self.assertEqual(n.run_once(self.conn, time.time()), 0)              # the old alert is not sent
        self.assertEqual(self.ntfy.posts, [])

    def test_thread_sends_and_stops(self):
        self.configure()
        old = notify.PASS_INTERVAL
        notify.PASS_INTERVAL = 0.2
        try:
            n = self.notifier()
            n.start()
            time.sleep(0.5)
            self.alert()
            deadline = time.time() + 5
            while not self.ntfy.posts and time.time() < deadline:
                time.sleep(0.05)
            self.assertEqual(len(self.ntfy.posts), 1)
            n.status('Sentinel stopped listening.')
            n.stop(timeout=5)                                                # one last pass sends it
            self.assertIn('stopped listening', self.ntfy.posts[-1]['body'])
        finally:
            notify.PASS_INTERVAL = old


if __name__ == '__main__':
    unittest.main(verbosity=1)
