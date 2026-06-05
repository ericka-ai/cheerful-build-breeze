#!/usr/bin/env python3
"""Re-download the UIC barcode public-key registry.

Source: https://railpublickey.uic.org/download.php

Usage:
    python refresh_certs.py

Overwrites uic_keys.xml in this directory. Commit the result.
"""
import os
import sys
import urllib.request

URL = "https://railpublickey.uic.org/download.php"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uic_keys.xml")


def main() -> int:
    print(f"Downloading {URL} ...")
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    if b"<keys>" not in data[:200]:
        print("Unexpected response (no <keys> root); aborting.", file=sys.stderr)
        return 1
    with open(OUT, "wb") as f:
        f.write(data)
    count = data.count(b"<key>")
    print(f"Wrote {OUT} ({len(data)} bytes, {count} keys).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
