# UIC public-key registry (918.3 / 918.9 signature verification)

`uic_keys.xml` is the official UIC barcode public-key list, downloaded from:

    https://railpublickey.uic.org/download.php

Each `<key>` entry contains:

- `issuerCode` — the issuing railway's RICS code (matches the RICS in the barcode header `#UT…`)
- `id` — the signature key id (matches the key-id field in the barcode header)
- `versionType` — `FCB` (918.9), `UIC 918-3`, `TLB`, `DOS`, `SSB`, …
- `signatureAlgorithm` — e.g. `SHA1withDSA(1024,160)`, `SHA256withDSA(2048,256)`, `SHA256withECDSA`
- `publicKey` — base64 of either a bare `SubjectPublicKeyInfo` or a full X.509 certificate

## How it's used

`ticket_webapp/app.py`:

- `_uic_load_key_store()` parses this XML into a lookup keyed by `"<rics>_<key_id>"`
  (with zero-pad-stripped aliases so `00008`/`0080` match `8`/`80`). The `publicKey`
  blob is loaded as a public key, falling back to extracting the key from an X.509
  certificate.
- `_uic_verify_signature()` looks up the key for the barcode's RICS + key-id and
  verifies the signature **over the compressed payload**:
  - UT01 (918.3): DER DSA signature, SHA-1.
  - UT02 (918.9): raw `r||s` (32+32) rebuilt into a DER signature; hash/curve chosen
    from `signatureAlgorithm` (DSA-SHA256/SHA224 or ECDSA-SHA256).
- If the signing key is **not** in this registry (many domestic German tickets are not
  published here), verification returns `valid = null` ("not verifiable") rather than a
  false negative.

## Refreshing

Run `python refresh_certs.py` to re-download the latest list. Commit the updated
`uic_keys.xml`.

## Attribution

Verification logic ported from TheEnbyperor/zuegli (`main/uic/certs.py`,
`main/uic/envelope.py`), EUPL-1.2.
