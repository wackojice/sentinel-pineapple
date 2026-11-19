# Sentinel: development notes

Everything technical that is not needed to install and use the module.

## Testing without a Pineapple

The engine can analyse a pcap file (classic pcap format, radiotap or raw 802.11):

```sh
pip install scapy                       # only needed to generate the test pcap
python3 tools/make_test_pcap.py test.pcap
python3 projects/Sentinel/src/assets/engine/engine.py --pcap test.pcap --db test.db
```

You can also feed it a real capture from `airodump-ng` or `tcpdump -i wlan1mon -w capture.pcap`. Convert `.pcapng` files with `editcap -F pcap input.pcapng output.pcap`.

## Tests

```sh
python3 tools/test_module.py      # module backend, standard library only
python3 tools/test_fetch_ipk.py   # offline install tool
python3 tools/test_detect.py      # intrusion detection, standard library only
python3 tools/test_install.py     # install.sh / uninstall.sh, with BusyBox when installed
pip install scapy
python3 tools/test_engine.py      # capture engine
```

`test_engine.py` replays a synthetic capture through the engine and checks security classification, hidden SSIDs, clients, probes, deauth counts, audit grades, channel attribution, the channel hopper and that corrupted frames never crash the parser.

`test_module.py` runs `module.py` against simulated radios (`iw` and `ip` are faked) and checks that the radio is freed before listening, that a slow start is not reported as a failure, that the engine state never comes from an old status, and that saving settings always ends with a monitor interface.

Self-test without scapy or Pineapple: `python3 tools/selftest.py` (DFS decoding, 20,000 malformed frames, privacy defaults).

## Building the module

Requirements: Node.js, npm and Python 3.

```sh
./build.sh package        # npm ci if needed, compile, Sentinel-<version>.tar.gz
```

`./build.sh release` builds everything a GitHub release needs into `release/`: the module, the exact
`python3-sqlite3` package (its SHA-256 is pinned in `vendor/python3-sqlite3.sha256`; it is downloaded from the
OpenWrt feed over HTTPS the first time and kept in `vendor/`, out of git), `install.sh`, `uninstall.sh`,
`install-from-pc.sh` (from `installer/`, with the version written in) and `SHA256SUMS`. `AUTO_INSTALL_DEPENDENCIES`
at the top of `module.py` (off) decides whether opening the module installs `python3-sqlite3` without a click.

The script stops at the first error, works from any folder, sets the legacy OpenSSL provider that the
Angular 9 toolchain needs on Node.js 17 and newer, leaves Python caches out of the package and stores every
file as owned by root.

## Demo and screenshots

`tools/demo_server.py` runs the real `module.py` on a synthetic capture of fictional networks, and `demo/` hosts the
web interface the way the Pineapple does. This is what produced `docs/screenshots/`.

```sh
python3 tools/demo_server.py &     # API on 127.0.0.1:8765
ng serve demo                       # http://localhost:4300
```

## Architecture

```
Web UI (Angular)  ⇄  module.py (Hak5 backend)  ⇄  SQLite  ⇐  engine.py (capture)
```

- **`assets/engine/engine.py`**: an independent background process. It reads frames from one `AF_PACKET` socket per radio, each radio hopping channels on its own with `iw`, and writes to SQLite in batches every 5 s (low CPU use, little flash wear). It keeps running when you leave the page.
- **`assets/engine/dot11.py`**: a dependency-free radiotap / 802.11 decoder in standard Python: beacons, probe requests/responses, deauth/disassoc, data frames, RSN IE (AKM, ciphers, PMF), WPA1, WPS and an access point fingerprint.
- **`assets/engine/store.py`**: SQLite schema, in-memory aggregation and the `events` table, the alert bus shared by every tab.
- **`assets/engine/analysis.py`**: read-side computations: channel report, security audit (with a separate score for your networks), spectrum and overview.
- **`assets/engine/nl80211.py`**: changes a monitor interface's channel through nl80211 directly (the message `iw dev … set channel` sends), so no process is started at each hop; the hopper falls back to `iw` if the device does not take it. Its `send` calls go to the local kernel over a netlink socket; nothing is transmitted over the air, and the capture socket is only read. Passivity check: `grep -rn "send" projects/Sentinel/src/` must only show those two lines.
- **`assets/engine/report.py`**: the Reports tab. Every hour while listening, the engine writes today's row in the
  `daily` table (scores, alerts, deauthentication frames; kept 400 days), which gives the trend. `build` puts the
  report together for 1, 7 or 30 days, with advice for each audit finding on your networks (`ADVICE`).
- **`assets/engine/muted.py`**: the alert types muted in the Detection tab (`muted_alerts.json`). The detector writes
  their alerts as already read.
- **`assets/engine/summary.py`**: once a minute while listening, and once when it stops, the engine writes
  `/tmp/sentinel-summary.json` (about 1 KB, root only): listening state and radios, your networks (marked, seen in the
  last hour, score, worst level, the ones not seen), unread alerts by severity and the last five, deauthentication
  frames in the last hour, and `generated_at` on the Pineapple's clock. A dashboard reads that file instead of
  starting Python on the Pineapple at every poll.
- **`assets/engine/mynets.py`**: your networks, in `my_networks.json` (64 at most): one reference per BSSID, frozen when it is marked, and suggestions of other access points of the same network.
- **`assets/engine/detect.py`**: passive intrusion detection. Every 5 s the engine hands it the window it aggregated in memory, before writing it; the detector reads it, keeps a bounded state (5,000 known BSSIDs, 256 followed, 1,024 cooldowns) and writes its events (`source = 'wids'`) in one transaction. A replayed pcap is cut into windows on the capture's own clock, so it gives the same alerts as the live run.
- **`module.py`**: starts and stops the engine, manages settings, detects the bands each radio supports (`iw phy`) and serves data to the UI.
- **UI**: Angular 9 and the same Angular Material components as the Pineapple interface (cards, tabs, buttons, toggles, selects, expansion panels), so Sentinel follows whichever Pineapple theme is active, light or dark. On load it reads the theme's colours from hidden Material elements and applies them to the hand-drawn parts (the shield, the gauge, the grade colours). The spectrum screens and the gauge are plain SVG, with no charting library.

Data lives in `/root/.Sentinel/` (`sentinel.db` and `settings.json`). The engine log is `/tmp/sentinel-engine.log`.

Default retention: channel and deauth statistics 48 h, devices 30 days, at most 5000 alerts.

## Known limitations

- A radio that hops between channels inevitably misses frames: traffic figures are relative trends, not absolute measurements.
- The 5 GHz recommendation ignores channel width (40/80/160 MHz) and DFS channels.
- Tested on a real Mark VII with the MK7AC (firmware 2.1.3): `test-report-0.4.3.md` and `test-report-0.4.4.md`. Intrusion detection (0.6.0) is covered by `tools/test_detect.py`; its thresholds and CPU cost still have to be checked on the device.
- Detection hears each channel only while the radio is on it (about 9 % of the time over 11 channels): a short burst can be missed.
- In Canada (and elsewhere), channels 120-128 are reserved for weather radar: the adapter refuses them and Sentinel skips them.
- CPU: the engine used about 40 % of the Mark VII's single core in that test (2 radios, a busy 2.4 GHz band). Every frame is decoded in Python and beacons are the expensive part.

## Radios: what Sentinel does at each start

Channels an adapter keeps refusing are skipped, listed in Settings, and tried again every few minutes.

Each time monitoring starts, Sentinel prepares the radios, because a reboot undoes both of these:

- A monitor interface it created (`wlan3mon`) is created again if it is gone. Choosing a non-monitor interface such as `wlan3` in Settings is fine: saving switches the radio to `wlan3mon`.
- A monitor interface cannot change channel while another interface of the same radio is up (`iw` answers "Resource busy"). The MK7AC's `wlan3` comes up in client mode at every boot, so Sentinel takes it down **when it is not connected to anything**. An interface in use (a connected client, an access point) is never touched: Sentinel then shows a warning and that radio stays on one channel until you disconnect it or turn off channel hopping. To get `wlan3` back afterwards: `ip link set wlan3 up`.

The engine needs 4 to 6 seconds to start on the Mark VII; the header shows "Starting…" until its first report.

## Offline dependency: `fetch_ipk.py`

Downloads `python3-sqlite3` from the Pineapple's own feeds on a trusted computer, so the Pineapple never needs
Internet access. Give it the list of installed packages: it then downloads only what is missing (on firmware 2.1.3,
just `python3-sqlite3`). Without that list it would also fetch newer copies of packages already installed, and
installing them would leave a mixed Python behind.

```sh
scp -O root@172.16.42.1:/etc/opkg/distfeeds.conf .
ssh root@172.16.42.1 opkg list-installed > installed.txt
python3 tools/fetch_ipk.py distfeeds.conf python3-sqlite3 --installed installed.txt --out ipk/
scp -O ipk/*.ipk root@172.16.42.1:/tmp/
ssh root@172.16.42.1 'opkg install /tmp/*.ipk && rm /tmp/*.ipk'
```

Tests: `python3 tools/test_fetch_ipk.py` (no network).
