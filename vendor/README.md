# vendor

- `distfeeds.conf`: the OpenWrt 21.02 feeds of the WiFi Pineapple Mark VII (firmware 2.1.3, `mipsel_24kc`).
- `python3-sqlite3.sha256`: the exact `python3-sqlite3` package validated on a real Mark VII (see
  `docs/test-report-0.4.3.md`). `./build.sh release` downloads it with `tools/fetch_ipk.py` and refuses any other
  file. The `.ipk` itself is not kept in git.
