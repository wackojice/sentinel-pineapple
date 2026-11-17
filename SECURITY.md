# Security policy

Sentinel runs as root on the WiFi Pineapple and reads frames sent by anyone in radio range, so security
reports are welcome.

## Reporting a vulnerability
Please **do not open a public issue**. Use GitHub's private reporting instead: **Security → Report a
vulnerability** on this repository. Include the version (`module.json`), what an attacker needs (radio range,
access to the Pineapple's web interface, a crafted file...), and how to reproduce it.

You will get an answer within a few days. A fix is published as a new release, and the report is credited
unless you prefer otherwise.

## Scope
- The capture engine and its decoder (`assets/engine/`): crafted frames must never crash it, make it transmit, or
  fill the flash.
- The module backend (`module.py`) and the web interface: injection, unsafe file handling, data exposure.
- `install.sh`, `uninstall.sh`, `install-from-pc.sh` and `tools/fetch_ipk.py`: integrity checks and safe paths.

Sentinel is passive by design: anything that makes it send a frame over the air is a serious bug.
