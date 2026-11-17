# Third-party components

## In the release files

### `python3-sqlite3_3.9.16-1_mipsel_24kc.ipk`
- **What:** the `python3-sqlite3` package of OpenWrt 21.02 for `mipsel_24kc`: Python's `sqlite3` module and its
  `_sqlite3` extension, built by the OpenWrt project. It is shipped unmodified, so that every Mark VII gets the
  exact package validated on a real device. Its SHA-256 is in `vendor/python3-sqlite3.sha256`.
- **Source:** https://downloads.openwrt.org/releases/packages-21.02/mipsel_24kc/packages/
- **Licence:** Python Software Foundation License Version 2 (PSF-2.0), the licence of Python and of its standard
  library. It allows redistribution of the binary, with the licence notice kept:
  https://docs.python.org/3.9/license.html
- **It uses, but does not ship,** `libsqlite3-0`, which is already on the Pineapple (SQLite is in the public domain).

## In the module

- **Angular project template, `api.service.ts`, `material.module.ts`:** from the official Hak5 module template,
  https://github.com/hak5/pineapple-modules
- **Angular and Angular Material** (MIT): the module is built against them; the Pineapple web interface provides
  them at run time.
