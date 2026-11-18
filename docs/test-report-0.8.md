# Sentinel 0.8.0: real-device test report

Device: WiFi Pineapple Mark VII + MK7AC, firmware 2.1.3. The Pineapple has no Internet access, PineAP is off,
and listening is passive only. The Pineapple's clock now comes from the computer it is plugged into (NTP over USB).

## Install and listening
- Upgrade from 0.7.5 with `sh install-from-pc.sh --reboot`, settings and marked networks kept.
- Both radios hop through nl80211: `wlan1mon` on the 11 channels of 2.4 GHz, `wlan3mon` on 25 channels of 5 GHz
  (120 to 128 skipped, weather radar). No error, 0 frames rejected out of more than 400,000.
- About 100 to 125 frames per second at home, well under the new budget (800 per second before only management
  frames are decoded). Engine memory 11 MB, as before.

## Recon while Sentinel is listening (test asked by the audit)
- A two-minute Recon scan was run from the Pineapple's interface while Sentinel was listening.
- **Sentinel:** kept running, no error, no frame rejected, both radios kept hopping, and it went on normally after
  the scan. The frame rate stayed in the usual range.
- **Recon:** did **not** find all the networks. Sentinel holds both radios: it hops channels on `wlan1mon`, and it
  takes the MK7AC out of managed mode (`wlan3` down) so it can hop on `wlan3mon`. Recon is left with a radio that
  keeps moving and without the 5 GHz adapter.
- **Result:** nothing crashes and nothing stays stuck, but the two cannot share the radios. Stop monitoring before a
  Recon scan (stopping brings `wlan3` back). Since 0.8.1 the main page says so while Sentinel is listening, and the
  README too.
