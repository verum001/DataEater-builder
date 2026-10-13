# Database security

See the [13 October 2026 audit](SECURITY_AUDIT_2026-10-13.md) for the Android and
Python implementation review, fixes, compatibility and limitations.

AES-256-GCM encrypts database contents under random keys. Creator signing keys
and content-key secrets are private files created atomically with owner-only
permissions. Preserve secure backups. Licences use a separate ECDSA P-256 key,
device-specific ECDH/HKDF wrapping and exact database identifiers. Newly issued
codes include encrypted-artifact fingerprints.

A public key supplied in the database is not independent proof of publisher
identity. Verify publisher key/artifact fingerprints through a trusted channel.
Signed expiry cannot be edited, but a customer-controlled clock or patched client
can defeat offline enforcement. There is no mandatory licensing server.
