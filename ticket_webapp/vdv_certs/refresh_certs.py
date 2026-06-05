#!/usr/bin/env python3
"""Refresh VDV-KA Sub-CA certificates from the official LDAP directories.

Requires the `ldapsearch` CLI (Debian/Ubuntu: `apt-get install ldap-utils`).
Writes `<prefix>_<ca_reference_hex>.der` files into this directory.

Source directories (see README.md):
  prod: ldaps://ldap-vdv-ion.telesec.de:636
  test: ldaps://vdv.test.telesec.de:636
"""
import base64
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))

DIRECTORIES = [
    ("prod", "ldap-vdv-ion.telesec.de", "ou=VDV KA,o=VDV Kernapplikations GmbH,c=de"),
    ("test", "vdv.test.telesec.de", "ou=VDV Sicherheitsmanagement,o=VDV KA KG,c=de"),
]


def fetch(host: str, base: str) -> str:
    env = {**os.environ, "LDAPTLS_REQCERT": "never"}
    out = subprocess.run(
        ["ldapsearch", "-x", "-H", f"ldaps://{host}:636", "-b", base, "-s", "sub",
         "(objectClass=*)", "cn", "cACertificate", "-LLL"],
        capture_output=True, env=env, timeout=120,
    )
    return out.stdout.decode("utf-8", "replace")


def parse_ldif(text: str):
    """Yield (cn, der_bytes) from LDIF, unfolding continuation lines."""
    lines = []
    for ln in text.split("\n"):
        if ln.startswith(" ") and lines:
            lines[-1] += ln[1:]
        else:
            lines.append(ln)
    cur = {}
    for ln in lines:
        if ln.strip() == "":
            if "cn" in cur and "der" in cur:
                yield cur["cn"], cur["der"]
            cur = {}
        elif ln.startswith("cn:"):
            cur["cn"] = ln.split(":", 1)[1].strip()
        elif ln.startswith("cACertificate::"):
            cur["der"] = base64.b64decode(ln.split("::", 1)[1].strip())
    if "cn" in cur and "der" in cur:
        yield cur["cn"], cur["der"]


def main():
    total = 0
    for prefix, host, base in DIRECTORIES:
        n = 0
        for cn, der in parse_ldif(fetch(host, base)):
            if der[:2] != b"\x7f\x21":  # only CV certs
                continue
            with open(os.path.join(HERE, f"{prefix}_{cn}.der"), "wb") as f:
                f.write(der)
            n += 1
        print(f"{prefix}: {n} certs")
        total += n
    print(f"total: {total}")


if __name__ == "__main__":
    main()
