# Sentinel 0.4.3: real-device test report

Device: WiFi Pineapple Mark VII, firmware 2.1.3 (OpenWrt 21.02.1, ramips/mt76x8, mipsel_24kc), plus MK7AC.
Conditions: the Pineapple has no Internet access, PineAP is off, and listening is passive only. The operator types the root password; Claude only guides the steps.
Rule: the code is frozen during the test. Every bug found becomes a GitHub issue.

## Step 1: system information
- OpenWrt 21.02.1 r16325-88151b8303, `DISTRIB_ARCH='mipsel_24kc'`.
- Already installed: `libsqlite3-0 3330000-1`, `python3-light/base 3.9.7-1`, `libpython3-3.9 3.9.7-1`.
  Missing: `python3-sqlite3`.
- Free space: 1.6 GB on `/`, 123 MB in `/tmp`.

## Step 2: offline dependency install
- The `packages-21.02` feed now serves Python 3.9.16 and libsqlite3 3.40, newer than what the firmware has.
  `fetch_ipk.py` would also have downloaded the dependencies that are already installed, at those newer
  versions: **issue #3**.
- Workaround: download only `python3-sqlite3_3.9.16-1_mipsel_24kc.ipk`. Its SHA-256
  (`b3d565e0…`) matches the feed index. It was copied Admin → Kali → Pineapple (`scp -O`), and the checksum
  was checked again on the Pineapple.
- `opkg install` installed **only** `python3-sqlite3`, with no other upgrade.
- `python3 -c "import sqlite3"` → `sqlite OK 3.33.0`. The 3.9.16 module works with the 3.9.7 interpreter.
- Module package `Sentinel-0.4.3.tar.gz`: its SHA-256 (`a24e9c27…`) matches the release. There was no existing `Sentinel` folder in
  `/pineapple/modules/`.

## Before step 3: test conditions fixed
- `iw dev` showed the Pineapple's client radio (`wlan2`) connected to the site's main Wi-Fi, which gave it LAN and
  Internet access (configured during the first setup). The operator disconnected it; the router no
  longer lists the Pineapple. No SSID is stored for client mode. The install above did not use the
  network (local .ipk file).
- The Open AP stays on (it cannot be switched off): it is hidden, with no impersonation, and not in the filter allow list.

## Step 3: module install
- Sentinel shows up in the module list, status "Stopped". Settings defaults are correct: tracking is off, and
  Radio 2 offers the 25 5 GHz channels including DFS.
- The suggestion banner "Use wlan3" shows up as expected. It was not used because of issue #2.
- Manual selection of `wlan3` (managed) is accepted, and monitoring starts with "wlan3 is not in monitor
  mode": **issue #6**. "Create wlan3mon" creates the monitor interface.
- The UI reported "Monitoring could not start", but the engine was simply slow to start: **issue #4**.

## Step 4: listening with two radios
From here on, the operator gave Claude a restricted SSH key: one forced-command script with a closed list of
passive actions, where every call is logged.
- `iw dev wlan3mon set channel 112` → `Resource busy (-16)`, because `wlan3` (managed) is up on the same phy:
  **issue #5**. After `ip link set wlan3 down`, channels 36, 112 (DFS) and 165 are accepted.
- Settings: radio 1 `wlan1mon`, 11 channels at 2.4 GHz; radio 2 `wlan3mon`, the 25 channels at 5 GHz (DFS
  included); 750 ms per channel; tracking off.
- Engine startup: 4 to 6 s (6 starts). `python3 -c "import sqlite3, json, socket"` alone takes 2.74 s.
- About 20 minutes of operation over 8 starts (configuration changes), both radios with `error: None` and no unusable channel, 0 frames rejected.
- After ~5 minutes: access points heard on 2.4 GHz channels 1/6/11, and on 5 GHz channels 44, **64 and 112 (DFS)**
  and 149.
- **15 of 15 reference BSSIDs** (3 access points × 5 SSIDs, inventory taken from the controller) were found,
  on the right channels (2.4 GHz 1/6/11; 5 GHz 64 and 112, both DFS). The security audit matches the
  controller: WPA2/WPA3 transition, PMF capable (optional).
- Privacy defaults: `clients` = 0 and `probes` = 0. Disconnections are still counted (4 entries, 5 frames).
- One engine stop during the test: the operator pressed "Stop" in the UI. This was not a bug (the status
  ended with `running: False` and no error).

## Step 5: CPU of `engine.py` (priority measurement)
Measurement method: CPU time accumulated by the process (TIME column of `top`) over a timed window of about 77 s, taken 30 s
after start. The `top` sampling itself is included and is the same for all three.

| Configuration | Average CPU |
|---|---|
| 2 radios: 2.4 GHz (11 ch.) + 5 GHz all (25 ch., DFS) | **41 %** |
| 1 radio: 2.4 GHz only | **35 %** |
| 2 radios: 2.4 GHz + 5 GHz without DFS (9 ch.) | **38 %** |

Instantaneous values swing between 5 % and 82 %. Most of the cost comes from the 2.4 GHz radio (a busy band,
about 115-170 frames/s), and adding the 5 GHz radio costs about 6 points. Adding DFS costs about 3 points. On the
single-core MIPS of the Mark VII, about 40 % of one core is significant but leaves room. Pistes, if needed: a
longer dwell, or not decoding data frames beyond the counters.

## Issues opened
- #1: Overview tiles at 0 when tracking is off (found in review).
- #2: "Use wlan3" without DFS (found in review).
- #3: `fetch_ipk.py` also downloads dependencies that are already installed.
- #4: 3 s start timeout is too short.
- #5: EBUSY on `wlan3mon` while `wlan3` is up.
- #6: non-monitor interface accepted, and stale "Listening" header.

## Verdict
Passive listening works on a real Mark VII + MK7AC, on both bands and DFS channels, with the privacy
defaults respected and no crash. Before general use, fix #5 (without that fix the 5 GHz band does not hop) and #4
(the false failure message). The others are UI comfort.
