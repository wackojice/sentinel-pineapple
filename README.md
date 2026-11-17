# Sentinel

**Give your idle WiFi Pineapple a second life: a quiet guard that checks your Wi-Fi posture.**

[Version française](README.fr.md)

![Sentinel's overview: live spectrum, your networks, alerts](docs/screenshots/1-overview.png)

## Why Sentinel?

Many WiFi Pineapples spend their days in a drawer. The pentest is over, the training is done, or someone tried it once
and never needed it again. It is still an excellent Wi-Fi radio.

Sentinel turns that Pineapple into a **passive watchdog for your own Wi-Fi**. Plug it in, open the module, and it tells
you:

- **how secure your networks are**, with plain-language explanations (WPA3, PMF, open networks, WPS…);
- **who else is on the air around you**, and which channel is the quietest;
- **when something looks like an attack**: someone copying your network's name, a burst of frames kicking devices off,
  a flood of fake access points.

Sentinel **only listens**. It never sends a frame, never attacks anything, and by default records nothing about
other people's devices.

## What you need

- A **WiFi Pineapple Mark VII** (firmware 2.1.3).
- Optional, but recommended: the **MK7AC adapter**, to watch the 5 GHz band (DFS channels included) as well as 2.4 GHz.
- A computer connected to the Pineapple (USB or its management Wi-Fi). **The Pineapple never needs Internet.**

## Install in two minutes

1. Download every file of the [latest release](../../releases/latest) into one folder: `Sentinel-<version>.tar.gz`,
   `python3-sqlite3_…_mipsel_24kc.ipk`, `install.sh`, `uninstall.sh`, `install-from-pc.sh` and `SHA256SUMS`.
2. From that folder, on your computer:
   ```sh
   sha256sum -c SHA256SUMS          # macOS: shasum -a 256 -c SHA256SUMS
   sh install-from-pc.sh --reboot   # asks for the Pineapple's root password
   ```
3. When the Pineapple is back (about two minutes), reload its web interface with **Ctrl+Shift+R** and open **Sentinel**.

The script checks every file, installs the module and its only dependency (`python3-sqlite3`, the exact package
tested on a Mark VII), and keeps your settings and data on upgrades.

<details>
<summary>Other ways to install</summary>

- **On the Pineapple itself:** copy the same files to a folder on the Pineapple and run `sh install.sh --reboot` there.
- **By hand:** extract the module into `/pineapple/modules/`, then install the dependency from the notice at the top
  of the module (this needs Internet on the Pineapple), or with `opkg install ./python3-sqlite3_…_mipsel_24kc.ipk`.
  Install **only** that package: the feed's other packages are newer than the firmware's.
- **Upgrading:** use the same commands. A reboot is needed after an upgrade, since the old module backend stays in
  memory until then.
</details>

## First start

1. **Settings:** Radio 1 is `wlan1mon` (2.4 GHz). Turn on Radio 2, pick the MK7AC (`wlan3`) and **5 GHz, all channels**.
   Save, then press **Start monitoring**.

   ![Settings: two radios, privacy switches off by default](docs/screenshots/4-settings.png)

2. **Mark your own networks.** In **Security**, type your network's name in the search box, then click the star at the
   top of the list: every access point of that network becomes yours. Sentinel also suggests the other networks of the
   same access point. You now get a score for **your** networks, and Sentinel knows what to protect.

   ![Security: your networks first, a star on each row, one at the top](docs/screenshots/3-security.png)

3. **Let it listen.** Alerts appear in **Detection**, with a badge on the tab.

## What you will see

| Tab | What it shows |
|---|---|
| **Overview** | Both bands as a live spectrum, coloured by security; your networks' score; the latest alerts. |
| **Channels** | Who uses which channel, and the quietest one for your own access point. |
| **Security** | Every network nearby, graded from Critical to Good, with the reason in plain words. |
| **Detection** | Alerts from the passive intrusion detection, by severity. |

![Detection: an imitation of your network, deauthentication bursts](docs/screenshots/5-detection.png)

<details>
<summary>Channels tab</summary>

![Channels: spectrum of one band, the quietest channel, usage per channel](docs/screenshots/2-channels.png)
</details>

## What it detects

| Alert | When |
|---|---|
| Imitation of your network | another access point announces your network's name (critical if its security is weaker) |
| Two devices, one address | your access point's address announces two securities or two fingerprints at once |
| Weaker security | your access point is suddenly announced with a weaker security, or without required PMF |
| Access point changed | your access point's fingerprint changed (often a router update: accept it in one click) |
| Channel change | your access point stays on another channel |
| Deauthentication burst | 10 deauthentication frames in 5 s, or 30 in a minute, on one access point |
| Forged access points | dozens of never-seen access points at once (they are kept out of the database) |
| Answers for any network | one access point announces 5 different names in a minute |

**Honest limits:** with two radios hopping across channels, each channel is heard only part of the time, so a very
short attack can be missed. Sentinel warns you; it never blocks or answers anything.

## Good to know

- **Private by default:** no device address (MAC) and no searched network name is recorded unless you turn tracking on.
  Deauthentication frames are counted per access point only.
- **Light on the Pineapple:** about 40 % of its single core with both radios, about 12 MB of memory, and the database is
  capped at 64 MB.
- While it listens, Sentinel switches off the idle `wlan3` so the 5 GHz radio can change channel. "Stop monitoring",
  a reboot or `uninstall.sh` give it back.
- Don't run Recon on the same radio at the same time. To use the Pineapple for something else, just stop monitoring.
- Channels 120–128 are refused in Canada (weather radar): that is normal.
- The Pineapple has no battery-backed clock. Times are shown on its own clock, and a note says when it drifts.

## Uninstall

```sh
sh /pineapple/modules/Sentinel/uninstall.sh            # keeps your data and python3-sqlite3
sh /pineapple/modules/Sentinel/uninstall.sh --purge    # also deletes /root/.Sentinel
```

<details>
<summary>What Sentinel stores, and where</summary>

- `/root/.Sentinel/sentinel.db`: access points (30 days), channel and deauthentication statistics per access point
  (48 hours), alerts (5,000 at most). Device addresses and searched names only if you turn tracking on.
- `/root/.Sentinel/settings.json` and `my_networks.json`: your settings and your marked networks.
- `/tmp/sentinel-*`: the engine's log, PID and radio state, gone at each reboot.
</details>

## More

- Test reports on a real Mark VII: [`0.4.3`](docs/test-report-0.4.3.md), [`0.4.4`](docs/test-report-0.4.4.md),
  [`0.6`](docs/test-report-0.6.md), [`0.7`](docs/test-report-0.7.md)
- How it works, tests, building, demo: [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)
- What may come next: [`docs/ROADMAP.md`](docs/ROADMAP.md)
- Changes: [`CHANGELOG.md`](CHANGELOG.md) · Security issues: [`SECURITY.md`](SECURITY.md) ·
  Third-party components: [`THIRD-PARTY.md`](THIRD-PARTY.md)
- Licence: MIT, by Not_Hackerman. Written with the help of the AI assistants Claude and Fable.

*The screenshots come from the demo, with fictional networks (`tools/demo_server.py`).*
