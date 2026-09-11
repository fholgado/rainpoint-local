# Security boundary

The current source candidate encrypts operational radio sessions, the management
API and OTA downloads using TLS-PSK. This requires the matching gateway, integration
and radio firmware; it is not yet deployed or physically qualified. Do not expose
listeners to the public Internet. Rollout status is in [the roadmap](PROJECT_ROADMAP.md).

TLS 1.2 uses the existing per-node 32-byte credential, or the separate management
credential for HA. The server permits only ECDHE-PSK/ChaCha20-Poly1305 and
PSK/AES-128-GCM; forward secrecy is not guaranteed when the latter is negotiated.
TLS authenticates peers and protects records against observation, alteration and
replay. Existing application authentication, command IDs and RF counters remain
necessary: encrypted transport is not permission to repeat a logical operation.
Session tickets are disabled, credentials are checked on each handshake, and
there is no automatic plaintext fallback. Python 3.13+ TLS-PSK support is required.
The implementation uses [Python's TLS-PSK interface](https://docs.python.org/3/library/ssl.html#ssl.SSLContext.set_psk_server_callback)
and the [ESP32 secure client's pre-shared-key support](https://github.com/espressif/arduino-esp32/blob/2.0.17/libraries/WiFiClientSecure/src/WiFiClientSecure.h).

## Initial setup remains a trusted-network operation

The temporary setup access point and initial HTTP adoption exchange are unchanged.
Home Wi-Fi details and the initial node credential are **not protected by the new
operational TLS channel during this handoff**. Only commission on a network you
trust, with physical access to the node. Password-protected setup is deferred by
the user; firmware signing is planned for alpha. TLS and artifact checksums do
not replace publisher signatures or secure initial provisioning.

## Authority and credentials

- Mutations require the gateway management bearer token inside TLS. Operational
  API connections also require a management or registered-node TLS credential;
  telemetry is no longer readable anonymously from the LAN.
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

The HTTP server permits at most 32 concurrent requests and the radio listener
at most 32 concurrent connections, including incomplete handshakes. TLS handshake
timeouts are bounded. Socket reads have a
10-second timeout; JSON bodies are limited to 16 KiB. Ambiguous body framing,
non-object JSON and non-finite JSON numbers are rejected. Event waits are finite
and limited to 30 seconds; event pages contain at most 1,000 records.

Firmware offers are bounded and checked against local file size and SHA-256 before
use. The ESP32 verifies the download and requires healthy gateway confirmation,
with rollback for an unconfirmed image. SHA-256 detects corruption; it is not an
asymmetric publisher signature. Keep a verified installed image and rollback
artifact when pruning offers.

The explicit `--insecure-development` CLI option is for isolated local test
harnesses only. It is not exposed in the gateway app's normal configuration.

Use private HA backups before deployment. Credentials, databases, installation
snapshots and raw RF recordings belong outside tracked release source. The source
packager includes tracked runtime paths only; CI checks a fresh empty installation.
