# Sentinel 0.4.4: real-device test report

Device: WiFi Pineapple Mark VII + MK7AC, firmware 2.1.3. No Internet, PineAP off, passive listening only.
The package was built from the repository (identical to Fable's build). The operator installed it and rebooted.

## State after the reboot, before the start (the #5 scenario)
- `wlan3mon` is gone; `wlan3` (managed) is **up** again; client mode is not connected.
- Settings still name `wlan1mon` and `wlan3mon`.

## Results
| Point | Result |
|---|---|
| #5: the 5 GHz radio changes channel after a reboot | **Confirmed.** At start, Sentinel took `wlan3` down by itself (it was up after the reboot; the operator did not touch it). `wlan3mon` hops: channel 100, then 136 within 25 s. No error. |
| #5: `wlan3` stays down while listening | **Confirmed.** `wlan3: <BROADCAST,MULTICAST> DOWN`. |
| Refused channels | 120, 124 and 128 are listed as unusable. Expected: in Canada these channels are reserved for weather radar. The radio skips them, and the others keep working. |
| Networks | 41 access points in the last hour (17 on 2.4 GHz, 24 on 5 GHz), on 5 GHz channels 44, 64, 112, 149 and 157. |
| #1: Overview tiles | **Confirmed.** "Off — connected devices are not tracked" and "Off — network searches are not tracked". |
| #4: start | **Confirmed.** "Start monitoring" shows "Starting…", then "Listening", with no failure message. |
| #6: header and interface | **Confirmed.** After stopping, the header shows "Stopped". Choosing `wlan3` and saving switches the radio back to `wlan3mon`. |
| #2: "Use wlan3" | Fix present in the installed bundle (`CH_5_ALL`). |
| Rejected frames | 0 |

## Observations
- **Recreating `wlan3mon` by hand.** After the reboot the operator selected `wlan3` and clicked "Create wlan3mon"
  before starting, because `wlan3mon` was no longer in the list. 0.4.4 recreates it at start anyway. A hint
  such as "will be recreated when monitoring starts" would avoid this manual step.
- **PID file: false alarm.** A check from the test script reported the engine as stopped while it was
  running. The PID file is present and correct (`/tmp/sentinel-engine.pid` = the running engine, which `top`
  also shows). The fault was in the test script: `ps w | grep` finds nothing on the Pineapple's BusyBox.
  This is not a Sentinel bug.
- **Clock.** The Pineapple has no RTC and no Internet: its clock went back about 2 h 30 at the reboot. Timestamps
  in the database (retention, "last hour") can be off.

## Issue status
- Confirmed and closed: #1, #2, #4, #5, #6.
- Still open: #3 (`fetch_ipk.py`; the README tells users to install only `python3-sqlite3`).
