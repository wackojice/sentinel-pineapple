# Changelog

## 0.9.1
- **Notifications tested end to end on a real Mark VII** (firmware 2.1.3): the test button and the engine's own
  messages reached the ntfy app on a phone, over HTTPS to ntfy.sh, with the Pineapple in client mode on `wlan2`.
  Sentinel kept listening on both radios the whole time.
- When listening stops, the "Sentinel stopped listening" message now goes out first, with at most 3 seconds to send
  it, before the slower steps (saving the last data, the dashboard summary). The module stops the engine for good
  after 5 seconds, so a slow server or a busy Pineapple could otherwise cut that message.

## 0.9.0
- **The Notifications tab: alerts on your phone through ntfy** (ntfy.sh or your own server).
  - Choose the server, a topic (a **Random** button makes one that is hard to guess), an optional access token, the
    minimum severity (high and critical by default) and a cap per hour. Muted alert types are never sent.
  - Beyond the cap, one message says how many alerts were held back.
  - Optional status messages: a radio stopped working or came back, listening stopped.
  - **Save and send a test** checks the settings right away.
  - Off by default. Nothing older than the moment you turn it on is sent.
- **How it runs.** A separate thread of the engine, with its own database connection, looks for new alerts every
  10 seconds. It never blocks listening; a message that fails is tried again on the next pass, and the last error
  shows in the tab. HTTPS goes through Python's ssl module, or through curl when the firmware has no ssl.
- **Privacy and safety.** The settings file is readable by root only. The access token is never sent back to the
  interface, written to a log, a report or the dashboard summary. Messages are plain text (no Markdown), control
  characters are removed and the length is capped, since network names come from anyone in radio range. The tab says
  that messages hold your network names and leave the house unless the server is yours, and that the Pineapple should
  reach it through client mode on wlan2, not the MK7AC.
- Tests: `tools/test_notify.py` (11, against a stand-in ntfy server) and 2 more in `tools/test_module.py`.

## 0.8.6
- **A designed HTML report.** The new **HTML** button downloads the report as one self-contained page (no external
  font, script or image: it opens anywhere, offline): a dark header with gauges for your networks and the
  neighbourhood, key figures, a day-by-day chart (both scores and the alerts of each day), what to change as a
  numbered list, your networks with PMF and WPS flags, alerts by type, and a strip of channels with the best one and
  yours highlighted. Severity is always written out, never shown by colour alone. It reads well on a phone too.
- **Print or PDF** now prints that same page instead of the plain black and white one.
- Network names and alert titles are escaped in the page: a name like `<img onerror=...>` shows up as text.

## 0.8.5
- **Reports: CSV and Markdown.** Next to **Print or PDF**, two buttons download the report:
  - **CSV**: one table with a `section` column (summary, trend, to_change, my_network, alert, channel...) to filter
    on in a spreadsheet;
  - **Markdown**: the same report as text, for notes or a ticket.
- Network names come from anyone in radio range, so the exports treat them as untrusted: in the CSV, a cell that
  starts with `=`, `+`, `-` or `@` gets a leading quote so a spreadsheet never runs it as a formula; in the Markdown,
  table separators, formatting, links and HTML are escaped.

## 0.8.4
- **The Reports tab.** A summary of the last 24 hours, 7 days or 30 days (7 by default):
  - your networks' score and the neighbourhood's, with a trend, one point per day;
  - **what to change** on your router, once per problem and the most serious first (turn on PMF, turn off WPS,
    replace WEP...), with the networks it applies to;
  - your networks one by one (band, channel, security, PMF, WPS, level), and the ones not seen in the period;
  - the alerts by type, and the most serious ones;
  - the best channel now in each band, next to yours.
- **Print or save as PDF** opens the report on its own page, in plain black and white, and calls the browser's print.
- The engine keeps one row per day (`daily` table, about 100 bytes, kept 400 days), updated every hour while
  listening. The trend shows up after two days of listening.
- Tests: 4 more (`get_report` checks its period; a row from the future is left out of the trend).

## 0.8.3
- **Mute a type of alert.** In Detection, open an alert and click **Mute** (for example "Channel change", when your
  own router moves channel on its own). Muted alerts are still recorded and shown, marked "(muted)", but they are
  written as already read: no more unread counter, tab badge or dashboard alert for them. Muting also marks that
  type's unread alerts as read. The list of muted types is at the top of the tab, with an **Unmute** button. Kept in
  `/root/.Sentinel/muted_alerts.json`.
- Tests: 4 more (`set_alert_muted` checks its parameters; a damaged file mutes nothing).

## 0.8.2
- The Recon warning on the main page has an **X** to close it. It stays hidden in that browser (it shows again in
  another browser, or if the browser's site data is cleared).

## 0.8.1
- **Recon.** Tested on the device: while Sentinel listens, a Recon scan misses networks, because Sentinel holds both
  radios (`wlan1mon`, and the MK7AC it takes out of managed mode). Nothing crashes, but they can't share. The main
  page now shows a warning the whole time Sentinel is listening: stop monitoring before a Recon scan. The README says
  the same. Test report: `docs/test-report-0.8.md`.

## 0.8.0
The last findings of the pre-release audit (P1), before a submission to Hak5.
- **A radio that stops working is reopened.** If an adapter is unplugged or its driver resets, Sentinel closes it,
  says so (the light turns orange: "Listening, with a radio problem") and tries again every 30 s. Before, it kept
  showing "Listening" on a dead radio. The status has a new `healthy` flag. (3.4)
- **A frame budget against floods.** Normal listening is about 150 frames/s. Above 800 per second only management
  frames are decoded, above 2,000 the rest is skipped and counted (`frames_over_budget`). A flood costs reading the
  socket, not decoding every frame. (4.1)
- **One forged beacon no longer changes the audit.** Within each 5 s window, an access point keeps the configuration
  it announced most often, not the last one. An access point seen only once in the period is not audited (yours
  always are). An address that announces two different configurations gets a note: usually a settings change or an
  update, sometimes someone imitating it. (6.1)
- **Recon.** While Sentinel hops channels on `wlan1mon`, a note under the header says it is the radio Recon uses,
  and to stop monitoring before a Recon scan. (3.2)
- Code: explicit UTF-8 for every text file, unused names removed (pylint). Builds from a clean copy under Node 16,
  like Hak5's check. Tests: 6 more (28 in `tools/test_detect.py`).

## 0.7.5
- **A summary for dashboards.** While listening, the engine writes `/tmp/sentinel-summary.json` once a minute (about
  1 KB, readable by root only): listening state and radios, your networks (score, worst level, the ones not seen in
  the last hour), unread alerts by severity and the last five, deauthentication frames in the last hour, and the
  time on the Pineapple's clock. A home dashboard can read it with a restricted SSH key instead of starting Python
  on the Pineapple at every poll. `uninstall.sh` removes it.
- Tests: 3 more for the summary (22 in `tools/test_detect.py`).

## 0.7.4
- **Without a 5 GHz adapter**, the Overview's 5 GHz panel says so ("No radio here receives 5 GHz. Plug in an
  adapter such as the MK7AC…") instead of showing an empty spectrum, or tells you to turn on Radio 2 when a 5 GHz
  radio is there but unused. Nothing else changes: Sentinel runs on 2.4 GHz only, with no error.
- **Settings follow what each radio can receive**, not its name: a 2.4 GHz-only radio shows only the 2.4 GHz preset
  and warns if 5 GHz channels are typed in; the hints describe the radio by its bands, and the 5 GHz adapter can have
  any interface name (`wlan3`, `wlan4`…). `uninstall.sh`'s manual hint is generic too.

## 0.7.3
- **A star at the top of the star column** marks every network shown, or unmarks them when they are all marked
  (half star: some are). "Shown" follows the search and the filters: search for your network's name, then one
  click marks all its access points. It asks for confirmation, since a neighbour marked by mistake would hide an
  imitation of it. It replaces the "Unmark all" link. New action `set_my_networks` (64 at most, one write).
- `SECURITY.md`: how to report a vulnerability privately. Test reports no longer describe the test site in detail.
- Tests: 2 more for the module (52).

## 0.7.2
- **"x min ago" is right even when the Pineapple's clock is not.** The Mark VII has no battery-backed clock and,
  without Internet, no way to set it: after each reboot it starts from an old date (found 2 days 10 hours behind
  on a real device, so alerts read "3 d ago"). `get_status` now sends the Pineapple's time, and the page measures
  every "ago" on that clock. When the two clocks differ by more than 10 minutes, a line under the header says so.
- Tests: 1 more for the module (50).

## 0.7.1
Installation without manual steps for the dependency.
- **Install scripts** in every release: `install.sh` (on the Pineapple), `install-from-pc.sh` (from a computer)
  and `uninstall.sh`. They check `SHA256SUMS`, refuse an archive that escapes its folder, keep
  `/root/.Sentinel`, install the exact `python3-sqlite3` validated on a Mark VII only when it is missing (Python
  3.9 and `mipsel_24kc` only), warn if another Python package changes, and say when a reboot is needed
  (`--reboot` does it). `uninstall.sh` undoes the radio changes Sentinel recorded; `--purge`, `--remove-sqlite`.
- **Dependency notice above every tab**: missing (a click installs it), installing, failed with the reason, and a
  warning if the install changed another Python package. No install without a click by default
  (`AUTO_INSTALL_DEPENDENCIES = False`).
- **Radios given back**: Sentinel records the interfaces it takes down and the monitor interfaces it creates
  (`/tmp/sentinel-radios.json`); "Stop monitoring" brings the former back up (audit 3.1).
- **Hardening**: `fetch_ipk.py` accepts HTTPS feeds only, requires the index checksum and plain file names, and can
  pin a file (audit 8.2); `build.sh` stops at the first error, needs no setup, and stores files as root without
  Python caches (8.4, 8.5); `./build.sh release`; `THIRD-PARTY.md`.
- Tests: `tools/test_install.py` (19, with BusyBox), plus 11 for the module (49) and 5 for `fetch_ipk.py` (9).

## 0.7.0
A lighter engine for the Mark VII's single core.
- **Beacon cache.** An access point sends about ten beacons a second, almost always identical. A beacon is now fully
  decoded only when its content changed; the timestamp and the TIM element, which change at every beacon, are left
  out of the comparison. Any other difference (security, name, fingerprint, size) means a full decode, so a forged
  copy of a known beacon is always decoded. Bounded (4,096 entries). Measured on a PC: 23 µs to 7 µs per beacon.
  Hits and misses are in the engine status (`beacon_cache`).
- **Channel changes without `iw`.** The channel hopper sends the nl80211 message `iw dev … set channel` sends,
  directly to the kernel, instead of starting a process about three times a second. If the device does not take
  it, the hopper falls back to `iw` by itself. The method in use is in the engine status (`channel_method`).
  Only the receiver is tuned: nothing is transmitted over the air.
- Tests: 8 more for the engine (30).

## 0.6.3
- **A more responsive interface on the Mark VII.** Measured on the device: the engine averages about 40 % of the
  single core, with bursts to 80 %, and the web interface waited behind those bursts. The live engine now runs at a
  lower priority (`nice 10`, audit 4.1): listening is unchanged, but the web interface and the module's answers
  go first. Detection itself costs almost nothing (40-41 % with or without it).
- **Calmer refreshes, shown on each tab.** Header every 10 s (was 5), Overview and Detection every 15 s (8 and 15),
  Channels and Security every 30 s (10 and 15), each waiting for the previous answer. Each tab says "Updates every
  N s · last update hh:mm:ss".

## 0.6.2
- **Unmark all** in the Security tab removes the star from all your networks at once, after a confirmation
  (new action `clear_my_networks`, which requires `confirm: true`).
- **Tick all / Untick all** in the suggestions card.

## 0.6.1
- **Better suggestions when you mark a network.** Sentinel now also suggests the other networks of the same
  access point ("same device"): vendors such as UniFi derive one address per network from the radio's base
  address, keeping its middle bytes. Three stars and a few ticks are enough to mark a three-access-point mesh with
  five networks each, instead of fifteen stars. Still nothing is ticked by default. Found on a real UniFi network.
- The suggestions card shows each network's name.
- README: reboot the Pineapple and reload the page without cache (Ctrl+Shift+R) after an upgrade.

## 0.6.0
Your networks and passive intrusion detection.
- **Your networks.** A star in the Security tab marks an access point as yours (one BSSID at a time, never a name
  alone). What it announces is frozen as its reference; other access points of the same network are suggested
  (same name and security, plus the same vendor prefix or a common fingerprint), none ticked by default. Your
  networks get their own score, come first in the list, are outlined in the spectrum, and have an Overview card.
  They are kept in `/root/.Sentinel/my_networks.json`, which "Clear collected data" keeps.
- **Intrusion detection (Detection tab).** Eight passive rules: imitation of your network, two devices on one of
  your addresses, weaker security, changed fingerprint, channel change, deauthentication burst, forged access
  points, access point answering for any name. Alerts have cooldowns, a cap of 60 an hour with a reserve of 20
  for attacks on your networks, no device address in their details, and a badge on the tab. Turn it off in
  Settings ("Intrusion detection").
- **Robustness (audit).** SSIDs are cleaned of control and direction characters (7.1); the Pineapple's own
  interfaces are never reported (6.5); lists are capped (7.2); all switches must be real booleans and numbers are
  bounded (2.2); the interface waits for each answer before asking again (7.3); the Overview score uses the
  same window as the Security tab (6.4).
- Tests: `tools/test_detect.py` (19), plus 14 for the module and 5 for the engine.

## 0.5.0
First public version. Fixes from the pre-release security audit (priority P0); no new feature.
- **The database can no longer fill the flash.** A flood of beacons with random BSSIDs (what `mdk4` does) created
  a new access point for every frame, kept 30 days. Now: at most 5,000 access points in the database, at most
  500 new entries (access points, clients, probes, deauth keys) per 5-second cycle, and a hard ceiling of 64 MB
  for the database file. Known access points keep being updated; what is dropped is counted
  (`dropped_by_limits` in the engine status).
- **A database error no longer stops the probe.** A full, locked or damaged database loses that batch, counts
  it (`db_errors`) and listening goes on.
- **Deauth records without device addresses.** With client tracking off, deauthentication and disassociation
  frames are counted per access point only, without the source and destination MAC addresses.
- **Data folder.** The module creates `/root/.Sentinel` itself, readable by root only (0700).
- **Demo.** `tools/demo_server.py` could send SIGTERM/SIGKILL to an unrelated process with PID 4242 when saving
  settings or clearing data in the demo; it no longer touches any process.
- README: accurate privacy and passivity statements, and an uninstall section.
- Author name: Not_Hackerman.
- **`fetch_ipk.py` downloads only what is missing (#3).** New `--installed` option (the output of
  `opkg list-installed`): packages the Pineapple already has are skipped, along with their dependencies, so a feed
  that has moved on to newer versions can no longer leave a mixed Python behind. Without the option, a warning is
  shown. Tests: `tools/test_fetch_ipk.py`. The module itself is unchanged.

## 0.4.4
Fixes for the issues found during the first test on a real Mark VII with the MK7AC (`docs/test-report-0.4.3.md`).
- **The 5 GHz radio can change channel (#5).** A monitor interface cannot change channel while another interface
  of the same radio is up, and the MK7AC's `wlan3` comes up in client mode at every boot. Before each start,
  Sentinel now takes the idle client-mode interfaces of a hopping radio down. An interface in use (a connected
  client, an access point) is never touched; a warning is shown instead. This runs at every start, so it also
  holds after a reboot. A radio that refuses every channel now reports an error instead of silently staying on
  one channel.
- **A slow start is no longer reported as a failure (#4).** The engine needs 4 to 6 s to start on the Mark VII
  and the module gave up after 3 s. The module now records the PID of the process it launched, answers at once,
  and the header shows "Starting…" until the first report. An engine that exits is detected and reaped.
- **The header no longer shows an old "Listening" (#6).** The state is computed by the backend
  (`stopped`, `starting`, `listening`, `stalled`) from a recent heartbeat written by the process that is running
  now. When the Pineapple stops answering, the header says so instead of keeping the last status on screen.
- **A non-monitor interface can no longer be saved (#6).** Saving switches the radio to `<name>mon`, creating it
  when needed.
- **Overview (#1).** With tracking off, the two device tiles show "Off" instead of a misleading 0.
- **"Use wlan3" (#2)** fills in all 5 GHz channels, DFS included, like the default.
- `iw` and `ip` are run through a helper that cannot raise, so a missing command is reported, not fatal.
- README: warning about installing only `python3-sqlite3` offline (#3 itself, in `fetch_ipk.py`, is still open).
- Tests: new `tools/test_module.py` (21 tests, standard library only) and one more test in
  `tools/test_engine.py` (13 tests).

## 0.4.3
- **Data traffic counts again with the privacy defaults.** With `track_clients` off (the default since 0.4.1),
  data frames were dropped before they reached the channel statistics, so the Channels tab and the channel
  advisor ignored all data traffic. They are now always counted; clients are still stored only when
  `track_clients` is on. Found by Fable during the review of the 0.4.2 merge.
- New test: 500 data frames on channel 11 with default settings give 500 data frames in `channel_stats`
  and an empty `clients` table (12 tests in `tools/test_engine.py`).

## 0.4.2
Merge of two independent 0.4.1 branches (one by Claude, one by Fable), with no conflicts.
- **Correct channel for 5 GHz networks.** The access point channel now comes from the DS Parameter Set or the
  HT Operation element (with a band check), not only from the radio channel at capture time, so a beacon heard
  on a neighbouring channel is no longer filed under the wrong channel. (Fable)
- **Refused channels are retried.** A channel that fails 3 times in a row is skipped, then tried again after
  5 minutes (the radio may only have been busy). A missing `iw` no longer kills the channel hopper. (Fable)
- **Monitor interfaces come back after a reboot.** When a configured `<radio>mon` interface is gone,
  Sentinel creates it again before starting the engine. The engine log file is now always closed. (Fable)
- **Unit tests.** New `tools/test_engine.py` (needs scapy): 11 tests. (Fable; the client/probe test now enables
  tracking explicitly, and a new test checks that nothing is stored with the privacy defaults.)
- **Repository layout.** The module now sits at the repository root (`sentinel-pineapple-module`); `build.sh`
  no longer depends on the folder name.
- Everything from Claude's 0.4.1 below: DFS channels, crash safety, privacy defaults, offline install, self-test.

## 0.4.1
- **All 5 GHz channels by default, DFS included** (36-64, 100-144, 149-165). Many access points sit on DFS
  channels (52-144); 0.4.0 never listened there, so those networks were invisible. Listening is receive-only,
  so DFS rules do not apply. Channels the radio or regulatory domain refuses are skipped automatically.
  New settings presets: "5 GHz, all channels" and "5 GHz without DFS"; channel 144 added.
- **The capture engine can no longer be stopped by a frame.** Any error while decoding or aggregating a frame
  is caught, counted (`frames_rejected` in the engine status) and logged a few times per error type.
  Note: fuzzing 0.4.0 with 200,000 mutated frames did not crash it; this is a safety net, not a fix for an
  observed crash.
- **Privacy by default.** `track_clients` is now off by default, and a new `track_probes` setting (off by default)
  controls whether the network names that nearby devices search for are stored. Both store data about other
  people's devices: enable them only for your own lab devices. Existing settings files keep their values.
- **Offline dependency install.** New `tools/fetch_ipk.py` downloads `python3-sqlite3` and its dependencies from
  the Pineapple's own feeds on a trusted computer (SHA-256 checked), so the Pineapple never needs Internet access.
- **Self-test without scapy.** New `tools/selftest.py` (standard library only) checks DFS decoding, robustness
  against 20,000 malformed frames and the privacy defaults.

## 0.4.0
- Initial public version: live spectrum (2.4 / 5 GHz), channel advisor, WPA3/PMF security audit, two radios.
