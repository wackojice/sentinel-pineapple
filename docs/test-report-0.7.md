# Sentinel 0.7.x: real-device test report

Device: WiFi Pineapple Mark VII + MK7AC, firmware 2.1.3. The Pineapple has no Internet access, PineAP is off,
and listening is passive only.

## 0.7.0: 12 hours of listening without attack
Measured without starting any Python process on the device before reading the load, since each one costs about
3 s of CPU.

| Measure | Value |
|---|---|
| `engine.py` CPU | **39 %** over 2 minutes, about 40 % on average over the whole night (4 h 15 of CPU in 10 h 40) |
| Load average (1, 5, 15 min) | **1.5 / 1.7 / 1.75**, against 2.4 to 2.8 in 0.6.x |
| Engine memory | **11.8 MB** resident, 11.0 MB at start: no leak |
| Device memory | 76 MB used, 129 MB available |
| Frames | **6.28 million** parsed, **0 rejected** |
| Channel changes | nl80211 on both radios all night, no fallback to `iw` |
| Alerts during the night | **none** (goal of roadmap section 8.2: no `deauth_flood` and no `beacon_flood` without an attack) |

- The lower load comes from changing channel through nl80211: no more `iw` processes waiting for the USB radio.
- The beacon cache brought the engine from 41 % to 36-40 %. Decoding beacons is only part of the work;
  receiving, counting per channel and aggregating remain.

## Clock (0.7.2)
- The Mark VII has no battery-backed clock and, without Internet, no way to set it. After each reboot it
  starts from an old date: it was found **2 days and 10 hours behind**, so alerts read "3 d ago" in the browser.
- 0.7.2 measures every "x ago" on the Pineapple's clock (`server_time` in `get_status`) and says so under the
  header when the two clocks differ by more than 10 minutes. Internal computations (last hour, cooldowns,
  retention) were already consistent, since they all use the Pineapple's clock.

## Scripted install and upgrade (0.7.3)
- An upgrade from 0.7.0 to 0.7.3 was done with `sh install-from-pc.sh --reboot` from the computer connected
  to the Pineapple, with no manual step. The checksums were verified, the module was replaced and the
  Pineapple rebooted.
- After the reboot and Ctrl+Shift+R, the module works, and settings, data and the 25 marked networks were kept.
  `python3-sqlite3` was already present and was left as it was. Both radios are back on nl80211.
- This was the last install path that had not run on a real device.
