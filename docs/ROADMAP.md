# Sentinel roadmap

Ideas and plans that are not built yet. Nothing here is a promise.

## Summary export for dashboards (done in 0.7.5)
The engine now writes `/tmp/sentinel-summary.json` once a minute (see `docs/DEVELOPMENT.md`). What is left is on
the dashboard side: an SSH key restricted with `command="cat /tmp/sentinel-summary.json"`, pulled by the dashboard
host and never pushed by the Pineapple.

## Explanations by a local LLM (optional, outside the Pineapple)
A language model running on another machine can read the same summary and:
- explain alerts in plain language;
- write a daily digest;
- answer questions about the networks nearby.

It explains; it never decides or acts. Detection stays with Sentinel's tested rules. A local model is
recommended: nearby network names and addresses should not leave the home.

## Before a submission to Hak5
- The P1 findings of the pre-release audit are fixed in 0.8.0 (3.2, 3.4, 4.1, 6.1, see the changelog).
- One test on the device is still to do: an install on a factory-reset Mark VII. The session with Recon running was
  done in 0.8.0 (see `docs/test-report-0.8.md`).

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
- The last tab announced as coming: drone Remote ID (passive). Reports came in 0.8.4, notifications through ntfy in
  0.9.0; other services (Discord, Telegram, a generic webhook) only if people ask.
- Channel width from the HT/VHT/HE elements, and occupancy from the BSS Load element.
- A "Tetra edition" for the 6th-generation Pineapple (NANO/TETRA), if Python 3 is available there. The capture
  engine is reused, and only the interface is rewritten for that module system.
