# VDV-KA PKI Certificates

These are the public **VDV-KA** card-verifiable (CV) certificates for the German
transit ticket PKI. They let the decoder resolve **any** Sub-CA by reference
instead of relying on a single hard-coded key.

## Source

Downloaded from the official VDV-KA LDAP directories:

- Production: `ldaps://ldap-vdv-ion.telesec.de:636`
  base `ou=VDV KA,o=VDV Kernapplikations GmbH,c=de`
- Test: `ldaps://vdv.test.telesec.de:636`
  base `ou=VDV Sicherheitsmanagement,o=VDV KA KG,c=de`

Each file is named `<prod|test>_<ca_reference_hex>.der` where the CA reference is
the 8-byte issuer identifier (e.g. `4445564456110416` = `DE VDV` Sub-CA serial 4,
year 2016).

## How they are used

`_vdv_load_cert_store()` in `app.py`:

1. Reads the root certs (Certificate Profile Id 7, self-signed, plaintext) as
   trust anchors.
2. For recoverable Sub-CA certs (signature only), recovers the content with the
   root key via ISO 9796-2.
3. Extracts each Sub-CA RSA public key and indexes it by CA reference.

The decoder then recovers the per-ticket EE (issuer) certificate with the
matching Sub-CA key, and finally recovers the ticket itself.

Logic ported from [TheEnbyperor/zuegli](https://github.com/TheEnbyperor/zuegli)
(`main/vdv/pki.py`, `iso9796.py`), EUPL-1.2.

## Refreshing

To pull newly issued Sub-CAs, run with `ldap-utils` installed:

```bash
python3 refresh_certs.py
```
