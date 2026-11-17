# Sentinel roadmap

Ideas and plans that are not built yet. Nothing here is a promise.

## Summary export for dashboards
- **Goal:** let a home dashboard or a monitoring tool show Sentinel's state without opening the Pineapple's
  web interface.
- **How:** once a minute, the engine writes `/tmp/sentinel-summary.json` (about 1 KB) from what it already
  holds in memory:
  - the listening state and the radios;
  - the score and worst level of your networks, and which marked access points are not seen;
  - unread alerts by severity, and the last five alerts;
  - deauthentication frames in the last hour.
- No Python process is started per read: on the Mark VII that costs about 3 s of CPU each time.
- **Read access:** a dedicated SSH key restricted with `command="cat /tmp/sentinel-summary.json"`, so that the
  reader can do nothing else. It is pulled by the dashboard host, never pushed by the Pineapple.

## Explanations by a local LLM (optional, outside the Pineapple)
A language model running on another machine can read the same summary and:
- explain alerts in plain language;
- write a daily digest;
- answer questions about the networks nearby.

It explains; it never decides or acts. Detection stays with Sentinel's tested rules. A local model is
recommended: nearby network names and addresses should not leave the home.

## Before a submission to Hak5
- Findings P1 of the pre-release audit:
  - 3.2: channel hopping on Recon's radio;
  - 3.4: a radio that disappears;
  - 4.1: a CPU budget during a frame flood;
  - 6.1: several beacons before auditing an access point.
- Two tests on the device: an install on a factory-reset Mark VII, and a session with Recon running.

## More detection rules
These ideas come from another open project, [blue-team-wifi-wids](https://github.com/SinLoops333/blue-team-wifi-wids)
(a PC-side WIDS that uses the Pineapple as a remote sensor). Only the ideas are reused, not the code: that
project has no licence.
- **PMKID and handshake harvesting.** EAPOL frames (data frames, LLC/SNAP type `0x888e`) that carry an RSN PMKID,
  or that come right after a deauthentication burst on the same access point, are the signs of someone collecting
  material to crack a Wi-Fi password offline. To respect the privacy defaults, the rule only counts frames per
  access point and stores no device address.
- **Beacon clone by timestamp (TSF).** Each access point has its own clock, carried in every beacon. A copy that
  uses the same BSSID cannot follow the real clock: two interleaved timestamp sequences, or a jump backwards, give
  it away. The beacon cache leaves the timestamp out of its comparison, so this rule reads the 8 bytes of the
  timestamp on its own, which is cheap.
- **An evaluation bench.** Labelled captures (normal life, and each attack) to measure missed detections and
  false alarms whenever a threshold changes.

## Later
- The tabs announced as coming: notifications (Pineapple notifications first, then ntfy or a webhook), drone
  Remote ID (passive), reports.
- Channel width from the HT/VHT/HE elements, and occupancy from the BSS Load element.
- A "Tetra edition" for the 6th-generation Pineapple (NANO/TETRA), if Python 3 is available there. The capture
  engine is reused, and only the interface is rewritten for that module system.
