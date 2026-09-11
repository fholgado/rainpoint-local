# Firmware publisher-signing design

Research date: 2026-09-11. This is a proposed contract, not evidence that
production keys, GitHub protections, signed releases, or device validation
have been provisioned. Project status belongs in [PROJECT_ROADMAP.md](../PROJECT_ROADMAP.md).

## Recommendation and current boundary

Use detached ECDSA P-256/SHA-256 publisher signatures over a small, strictly
encoded artifact descriptor. Verify independently in the gateway and ESP32.
Keep the current TLS-PSK transport, streaming SHA-256 check, and trial/rollback
behavior; publisher authentication supplements them.

Current [ota_trial.cpp](../firmware/rainpoint_bridge/src/ota_trial.cpp) trusts
gateway-provided version, size, and hash. It calls `Update.begin` and writes
the inactive slot before completing the hash check, then calls `Update.end`
only on success. [package_alpha.py](../tools/package_alpha.py) prepares an
unpublished, clean-revision-bound bundle and checks USB parts/partition layout;
its checksums do not authenticate a publisher.

The installed framework package is `3.20017.241212+sha.dcc1105b`, Arduino
2.0.17, with Mbed TLS 2.28.7. Its ESP32 `dio_qspi/include/sdkconfig.h` enables
`CONFIG_MBEDTLS_ECDSA_C` and `CONFIG_MBEDTLS_ECP_DP_SECP256R1_ENABLED`;
`mbedtls/esp_config.h` enables SHA-256. Upstream identifies Arduino 2.0.17 as
ESP-IDF 4.4.7. No framework upgrade is needed to expose the primitives, but
a real target build and negative-vector execution remain necessary evidence.
[Arduino release](https://github.com/espressif/arduino-esp32/releases/tag/2.0.17),
[Mbed TLS 2.28.7 ECDSA API](https://mbed-tls.readthedocs.io/projects/api/en/v2.28.7/api/file/ecdsa_8h/).

## Proposed exact descriptor and signature contract

Use a new versioned signature schema, separate from the existing manifest
schema. Do not sign pretty-printed JSON or implement general JSON
canonicalization on the microcontroller. Construct these ASCII bytes in this
exact order, with one LF after every line, including the last:

```text
rainpoint-firmware-signature-v1
key_id=<key-id>
product=rainpoint-radio-node
board=esp32dev
hardware_profile=esp32dev-cc1101-v1
environment=rainpoint_bridge
firmware_variant=unified
channel=experimental
network_protocol_version=2
version=<version>
source_commit=<full-lowercase-40-hex-git-commit>
release_id=<release-id>
size_bytes=<decimal-size>
sha256=<lowercase-64-hex-image-digest>
```

Contract choices: maximum 768 encoded bytes; `key_id` is 1–32 characters
`[a-z0-9-]`; version is 1–48 ASCII characters satisfying the repository's
SemVer-compatible grammar; `release_id` is 1–96 characters `[a-z0-9.-]`.
Size is an integer, not a boolean, within the existing OTA size bounds;
encode in base 10 without signs or leading zeroes. All other fields above are
literal or have the stated exact format. Reject CR, embedded LF, NUL,
non-ASCII, duplicate JSON keys, missing fields, unsupported fields/schema,
and incompatible constant values. Prefer fixed-size buffers and explicit
length checks over dynamically serializing arbitrary objects. Golden vectors
must lock the exact bytes in both languages.

The outer JSON envelope transports the validated descriptor fields plus
`signature_algorithm: ecdsa-p256-sha256` and `signature_der_hex`. Only that
algorithm is accepted; no algorithm negotiation. Encode the ECDSA `(r,s)`
signature as ASN.1 DER, then lowercase hex (maximum 72 DER bytes / 144 hex
characters). Reject malformed DER and trailing bytes. Sign the descriptor
bytes with SHA-256 exactly once. On Python, `cryptography` supports
`ec.ECDSA(hashes.SHA256())`; on ESP32, hash the descriptor and pass its
32-byte digest to `mbedtls_ecdsa_read_signature`. Do not inadvertently hash
that digest a second time. These libraries already implement the signature
operation/encoding; do not implement ECDSA arithmetic.
[Cryptography ECDSA](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ec/),
[RFC 3279 signature encoding](https://www.rfc-editor.org/rfc/rfc3279.html#section-2.2.3),
[Mbed TLS verifier](https://mbed-tls.readthedocs.io/projects/api/en/v2.28.7/api/file/ecdsa_8h/).

This binds the bytes, version, release identity, source, and install target.
Download URL and local command ID remain gateway transport data, never trust
anchors. Human release notes remain explicitly unsigned display text. Any
future compatibility override or security-relevant policy needs a new signed
field/schema, not an unsigned catalog flag that relaxes the signed boundary.
The signature is not the artifact identity: use the signed image SHA-256.

## Verification and trust provisioning

- **Gateway:** pin a reviewed public-key allowlist; parse strictly; verify
  descriptor signature and compatibility before accepting a catalog entry or
  scheduling an update. Read and hash the actual complete local artifact before
  issuing a node command. Revalidate at use, and prevent file replacement
  between verification and serving (immutable snapshot/open descriptor).
- **ESP32:** compile only the public key and key ID into the production image.
  Load the P-256 group and validated public point, verify the descriptor before
  any `Update.begin` call, and derive version/hash/size from that authenticated
  descriptor. Reject mismatching duplicate command fields. Continue hashing
  downloaded bytes and abort on mismatch before `Update.end` or reboot.
- **Alternatives:** gateway-only verification is smaller but leaves a
  compromised gateway able to instruct arbitrary firmware installation.
  Node-only verification protects that boundary but misses early catalog/USB
  screening. Both checks are the recommended scope.

Provision the initial public key through a reviewed trusted USB baseline and
gateway package, not from the same untrusted download being verified. The
public key may be distributed openly; no private key belongs in firmware,
source bundles, build flags, CI caches, PR jobs, logs, or release assets.
Do not silently fall back to unsigned OTA when a key/signature is absent.
An unsigned legacy baseline requires a separately authorized trusted initial
flash; application-level verification cannot authenticate its own bootstrap.

This is application-level OTA authentication, not hardware Secure Boot:
physical reflashing, an already-compromised application, and local gateway
software replacement are outside its protection. Secure Boot involves a
bootloader/eFuse trust chain and separate irreversible hardware decisions;
do not enable it as an incidental signing change.
[Espressif Secure Boot](https://docs.espressif.com/projects/esp-idf/en/v4.4.7/esp32/security/secure-boot-v1.html).
Signed old images can still be replayed unless a separate monotonic-version
policy is implemented. Preserve deliberate trial rollback. Rotate public keys
through a release trusted by the old key before removing the old key; retain
a documented USB recovery path. Key compromise needs an explicit recovery
decision, not trust in a newly downloaded replacement key.

## Protected GitHub release workflow

Recommended job boundary: `prepare -> approved-sign -> approved-publish`.
Preparation runs tests/builds and produces an unpublished artifact at an exact
protected-branch commit; it has read-only repository access and no signing
secret. Signing runs on a fresh GitHub-hosted runner with a dedicated
`firmware-signing` environment. Publication is another job/environment with
only the write permission needed to publish and no signing secret.

Use manual dispatch restricted to the protected default branch; resolve and
record the immutable source SHA, and reject a selected candidate not tied to
that trusted run/SHA. Do not consume arbitrary PR-produced artifacts in a
privileged follow-up. Download only the same trusted run's explicit artifact,
treat it as data, recompute hashes, and run only reviewed signing/verification
code. Pin release-job actions to full commit SHAs and keep private-key exposure
to the signing step. Store the production private key only as an environment
secret initially; an independently operated KMS/HSM with constrained OIDC is
a later stronger isolation option. A job able to use a secret can exfiltrate
it: approval is not a cryptographic sandbox.
[GitHub secure workflow guidance](https://docs.github.com/en/actions/reference/security/secure-use).

For a public repository GitHub Free/Pro/Team supports environment secrets and
required reviewers. Configure exact allowed branch rules, a required reviewer,
and disable administrator bypass. Only one listed reviewer must approve;
listing several does not require all of them. Preventing self-review requires
another person: a sole maintainer must choose self-approval explicitly or add
a trusted reviewer. The default admin bypass is enabled. Avoid relying solely
on “protected branches only”: with no branch protections, that option allows
all branches. Environment restrictions match the workflow ref, not an
arbitrary commit supplied as an input. Protect workflow/signing-tool edits
and review the actual resolved commit and artifact. These settings require
out-of-band repository configuration; YAML alone is not proof of protection.
[GitHub environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments).

Signing is automatic *after* environment approval; build preparation is not
release publication. Keep `package_alpha.py` deterministic and secret-free.
A separate signing tool adds the envelope to staged artifacts and verifies it
with the pinned public key before publication. Refuse dirty candidates and
replacement of an existing release identity. Default local/CI artifacts remain
unpublished; an explicit separately authorized publication action creates the
GitHub prerelease. ECDSA signatures need not be byte-for-byte deterministic,
so unsigned-bundle reproducibility and signed-bundle authenticity are separate
tests. No key creation, secret upload, release, or device flash is authorized
by this design note.

## Verification evidence required

Use a clearly test-only key with no production trust. Cover golden canonical
bytes, a valid Python-signed vector verified by the ESP32 implementation,
wrong key/unknown key ID, missing signature, malformed/trailing DER, byte
tampering, every signed field changed independently, wrong board/profile,
oversize input, duplicate keys, and hash/size mismatches. Build checks must
prove test keys cannot enter the production trust allowlist and private-key
files cannot enter archives/caches. Release verification must reject a signer
whose public key differs from the compiled/distributed trusted key.

Instrument the updater so invalid signatures/metadata assert **zero calls to
`Update.begin` and zero flash writes**. Gateway artifact tampering should be
rejected before any node update request. Node download tampering must assert
`Update.abort`, no `Update.end`, no pending trial flag, and no reboot. With
the existing streaming design, this last test cannot assert zero inactive-slot
writes: the complete digest is unknown until download ends. Requiring *all*
image-byte verification before *any* flash write needs a separately designed
bounded full-image staging medium; merely downloading twice does not prevent
the second response changing. Test that limitation honestly.

Finally test trial health confirmation/rollback remains unchanged, and perform
an explicitly authorized isolated hardware trial only after host tests and
the production target compile pass. No new live valve transmission is part
of firmware signing validation.
