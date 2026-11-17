# Sentinel 0.6.x: real-device test report

Device: WiFi Pineapple Mark VII + MK7AC, firmware 2.1.3. The Pineapple has no Internet access and PineAP is off.
Versions installed in turn: 0.6.0, 0.6.1, 0.6.2 and 0.6.3. Network names and addresses of the test site are
left out of this report.

## Installation and upgrade
- After extracting a new version, the **module backend (`module.py`) stays in memory**: the page was new but the
  backend was old ("No action handler registered for action set_my_network"). A **reboot** fixes it.
- The browser may then keep the old interface: **Ctrl+Shift+R** is needed.
- Both points are now in the README (Install, "Upgrading?").

## My networks
- The test site has a mesh of three access points from one vendor (UniFi), with five networks each, so 15 BSSIDs.
  The site also has hidden mesh links between the access points, an ISP modem's own Wi-Fi with its hidden
  networks (kept on purpose outside the main network), and a printer's Wi-Fi Direct.
- **0.6.0**: suggestions only linked the same network on another access point with the same vendor prefix. Access
  points with different prefixes were not linked, so 15 stars had to be set by hand.
- **0.6.1**: "same device" suggestions (one address per network, derived from the radio's base address). Checked
  on the device: marking one network of an access point suggested its other networks plus its hidden networks,
  all correctly attributed. The hidden networks were checked against the controller: one is the mesh link that
  another access point uses.
- **0.6.2**: "Unmark all" and "Tick all / Untick all" work. Final list: 25 marked BSSIDs.
- With unmarked access points of a marked network, "Imitation of your network" alerts appeared, as expected. They
  stop once every access point of the network is marked.

## Detection
- Deauthentication frames are counted per access point, with no device address (0 rows with `src`/`dst`).
- About 466 deauthentication/disassociation frames in one hour, spread over 379 rows (access point × minute ×
  reason). This is consistent with normal band steering and idle timeouts, not with a single burst.
- The operator ran a deauthentication test on one of the marked networks and reports that the module behaved
  as expected. The rules, thresholds and limits that apply to such a test are documented in the README.
- **Still running:** 24 hours of listening without an attack. The goal is zero `deauth_flood` and zero `beacon_flood`
  (roadmap, section 8.2).

## CPU (Mark VII, single core)
Method: CPU time accumulated by the process (`top` TIME column) over a timed window.

| Measure | Value |
|---|---|
| `engine.py`, two radios, all 5 GHz channels, with detection | **41 %** on average (the same as 0.4.3 without detection), peaks at 80 % |
| `module.py` (answers to the page) | about 4 % |
| Pineapple web server | about 4 % |
| Load average | 2.4 to 2.8 |

The load average overstates the real use. It counts the `iw dev … set channel` processes and the USB radio
workers that wait for the hardware (state `D`), about three channel changes per second. Detection costs almost
nothing. The interface felt slow because the page's requests waited behind the engine's peaks.

**0.6.3**: the live engine runs at `nice 10`, and the page refreshes every 10/15/30 s, shown on each tab. Planned for
0.7: decode a beacon only when it changed, and change channel without starting `iw`.
