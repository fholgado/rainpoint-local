# Security boundary

RainPoint Local currently assumes a trusted, isolated local network. The gateway
API uses HTTP and the ESP32 session uses shared-secret HMAC authentication over
TCP. Neither transport is encrypted. Do not expose either listener to the public
Internet. Encryption, per-message replay protection and signed firmware are
publication gates in [the roadmap](PROJECT_ROADMAP.md).

## Authority and credentials

- Mutations require the gateway management bearer token. Read-only telemetry is
  available on the local API without that token.
- Standalone setup codes are one-use and accept at most five attempts per minute
  across the gateway. HA Supervisor discovery supplies add-on credentials privately.
- Rotation immediately invalidates the previous management token. Persistence uses
  an exclusive temporary file with private permissions, fsync and atomic replacement.
- Each radio has its own credential. A fresh nonce binds authentication to the
  node and protocol version; revocation disconnects the registered node.
- Sensor ACK ownership is persistent and single-node. Reassignment revokes the old
  owner before authorizing another transmitter.
- Valve commands use an evidenced association and persisted counter; a caller cannot
  supply arbitrary RF identities to the normal device-control API. Restart never
  replays a speculative open or close.

## Resource and update boundaries

The HTTP server permits at most 32 concurrent requests. Socket reads have a
10-second timeout; JSON bodies are limited to 16 KiB. Ambiguous body framing,
non-object JSON and non-finite JSON numbers are rejected. Event waits are finite
and limited to 30 seconds; event pages contain at most 1,000 records.

Firmware offers are bounded and checked against local file size and SHA-256 before
use. The ESP32 verifies the download and requires healthy gateway confirmation,
with rollback for an unconfirmed image. SHA-256 detects corruption; it is not an
asymmetric publisher signature. Keep a verified installed image and rollback
artifact when pruning offers.

Use private HA backups before deployment. Credentials, databases, installation
snapshots and raw RF recordings belong outside tracked release source. The source
packager includes tracked runtime paths only; CI checks a fresh empty installation.
