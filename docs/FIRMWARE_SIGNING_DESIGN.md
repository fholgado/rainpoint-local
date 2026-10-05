# Firmware publisher-signing design

Publisher authentication contract. Project provisioning, rollout and qualification
status belongs in [PROJECT_ROADMAP.md](../PROJECT_ROADMAP.md).

## Recommendation and current boundary

Use detached ECDSA P-256/SHA-256 publisher signatures over a small, strictly
encoded artifact descriptor. Verify independently in the gateway and ESP32.
Keep the current TLS-PSK transport, streaming SHA-256 check, and trial/rollback
behavior; publisher authentication supplements them.

[ota_trial.cpp](../firmware/rainpoint_bridge/src/ota_trial.cpp) verifies the
publisher signature and bound request fields before HTTP and `Update.begin`.
It writes the inactive slot while hashing the download, then calls `Update.end`
only on a matching digest. [package_alpha.py](../tools/package_alpha.py) prepares an
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

## Exact descriptor and signature contract

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

### Development versus production

Production images compile only `firmware_keys/` (release public keys).
Test images built with `RAINPOINT_DEVELOPMENT_OTA=1` and an explicit prerelease
version also compile `firmware_development_keys/`. Their authenticated hello
advertises `firmware_development_ota`. A trusted application-only USB flash
bootstraps this test trust without erasing node configuration or associations.
Returning the radio to a production image removes development trust.

`.github/workflows/sign-development-firmware.yml` is maintainer-dispatched on
`main` or `codex/*`, with no reviewer gate. Its separate
`firmware-development-signing` environment holds only
`FIRMWARE_DEVELOPMENT_SIGNING_KEY_PEM`; it cannot access the production secret.
Build/test jobs have no signing credentials. The fresh signing job uses the
development key and emits an unpublished artifact; it never deploys automatically.

Development key IDs use the `rainpoint-development-` namespace. The gateway
derives the required node capability from this **signed** identity, rejecting
catalog edits that try to offer development signatures to production radios.
The production radio independently rejects that key before downloading or
writing flash. Default packaging/staging remains release-key-only; development
staging must be explicit. The existing protected release environment and
human approval below are unchanged, including research images intentionally
deployed to installed garden radios under the release key.

The repository now includes `.github/workflows/sign-firmware.yml` and
`tools/sign_firmware.py`. Manual dispatch on protected `main` builds without the
signing key, then waits for the `firmware-signing` environment before signing.
It produces a short-lived **unpublished CI artifact**, not a GitHub release and
not an automatically installed update. Dispatch is not part of ordinary CI.

Before enabling it, a maintainer must provision all of the following together:

- A reviewed P-256 public key at `rainpointd_addon/rainpointd/firmware_keys/rainpoint-release-2026.pem`.
- Environment secret `FIRMWARE_SIGNING_KEY_PEM` containing the matching private
  PKCS#8 PEM, and environment variable `FIRMWARE_SIGNING_KEY_ID`.
- The `firmware-signing` environment with a required reviewer, administrator
  bypass disabled, and exactly one custom deployment rule: branch `main`.
- Protection for `main` and reviewed changes to the workflow/key/tooling.

The preflight queries GitHub and refuses missing/relaxed protection. The signer
checks the build receipt against the workflow's immutable commit and actual
image hash/size, refuses a private/public key mismatch, and verifies its output.
The private key is supplied only to that signing step; verification and artifact
upload run without it. Provisioning evidence is recorded in the roadmap. A sole maintainer must explicitly decide whether to allow
self-approval or appoint another reviewer; YAML cannot make that decision.

The temporary-key tests cover strict descriptor bytes, each bound field, wrong
keys, damaged images, malformed signatures, duplicate JSON and environment
protections. Gateway and ESP32 enforcement use the same package-pinned public key. On the
wire, the exact descriptor bytes are lowercase hex in `signed_descriptor_hex`,
with `signature_der_hex`; the OTA-only flat JSON parser rejects duplicates,
unknown fields and escape/nesting ambiguity. The radio command limit is 3072
bytes. Cryptographic checks use Mbed TLS, not custom ECDSA code. Runtime and
hardware qualification evidence remains in the roadmap.

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

### Release approval from chat

The maintainer may approve a specific release signing run by typing or speaking
approval in this chat. The agent then submits the environment review through the
maintainer's authenticated GitHub CLI account. Mobile GitHub approval is optional;
the required reviewer, protected `main`, disabled administrator bypass and
GitHub-held signing key remain unchanged. Development signing remains automatic
under its separate key/environment.

1. Identify the run, profile/version and immutable source commit for the user.
   Accept a clear approval for that candidate, including a reply to that request;
   general permission to continue development is not release approval.
2. Check the run is the repository's release-signing workflow on `main`, its
   source SHA matches the approved candidate, and `prepare` succeeded. Fetch
   `/repos/fholgado/rainpoint-local/actions/runs/{run_id}/pending_deployments`
   and select only `firmware-signing` with `current_user_can_approve: true`.
3. Submit `POST` to that same endpoint with `environment_ids` containing the
   selected environment ID, `state: approved`, and a comment stating that the
   maintainer explicitly approved the identified candidate in chat. Submit
   only while that review is pending; an already completed run needs no review.
4. Confirm successful signing, then independently verify the downloaded image,
   receipt, source SHA, version and signature against the pinned release public
   key. Report the result. Signing alone does not publish or install firmware.

If GitHub does not permit the authenticated account to review the deployment,
report that limitation rather than weakening the environment protection.
See [GitHub's deployment-review API](https://docs.github.com/en/rest/actions/workflow-runs#review-pending-deployments-for-a-workflow-run).

## Release discovery and version compatibility

GitHub Releases should be the publication and discovery source for released
radio firmware, but it is not the runtime compatibility authority. The
gateway owns firmware selection because it already knows each node's hardware
profile, firmware variant, channel, protocol version and capabilities. The HA
integration continues to expose the gateway-selected candidate through its
firmware Update entity and requests installation; it must not independently
interpret GitHub tags, choose an image or bypass the gateway catalog.

Keep three independently versioned products: the HA integration, the gateway
app and the radio firmware. Do not require their SemVer values to match. Their
contracts meet at two explicit seams:

- Firmware-to-gateway compatibility uses the node network-protocol range,
  required/provided capabilities, hardware profile, firmware variant and
  release channel.
- Gateway-to-integration compatibility uses a versioned public response schema
  and capabilities. Add an integration minimum only when a firmware feature
  truly changes the HA-facing schema; otherwise preserve the stable gateway
  interface.

A catalog schema v2 must authenticate every compatibility field that can admit
or reject an update. At minimum it carries the immutable release ID, firmware
version, hardware profile, variant, channel, network-protocol range, required
gateway capabilities, compatible source variants/versions, artifact size and
digest, source commit, release URL and rollback policy. A signed, monotonic
catalog generation prevents an older valid index from silently replacing a
newer one. These fields require a new signed descriptor schema; they must not
be added as unsigned flags around the existing v1 descriptor.

Implement release discovery as another gateway catalog adapter alongside the
strict local catalog. It reads a bounded signed index from a fixed GitHub
Release asset, verifies it with the provisioned publisher trust, downloads the
exact immutable asset, verifies its size, digest and artifact signature, then
stages it locally. The existing local adapter remains available for development,
offline installation and recovery. Nodes continue downloading from the local
gateway rather than GitHub, so a staged update remains usable without Internet
access and the node does not need GitHub/TLS trust machinery.

Persist only a fully verified last-known-good index and artifacts. If GitHub is
unavailable, the index is malformed, its signature or generation is invalid,
or no candidate satisfies the complete contract, expose no new update and keep
the running firmware untouched. Do not follow raw branch files, mutable
"latest" binary URLs or workflow artifacts. Normal releases use immutable
GitHub Release assets; stable, beta and research channels require explicit
selection, and research builds never appear on the stable channel.

The release pipeline builds an image once at an immutable source commit, runs
the protocol and compatibility matrix, signs the artifact and index, and only
then publishes through the approved release environment. When a change is not
backward compatible, publish and install in dependency order: integration
support first when the HA schema changes, gateway support second, and firmware
last. HACS remains responsible for integration updates and the HA app repository
for gateway updates; the firmware Update entity is intentionally separate.
Start with user-approved firmware installation rather than automatic rollout.

Qualification must cover wrong hardware/profile/variant/channel, older and
newer network protocols, missing capabilities, incompatible gateway/API
schemas, tampered index and artifact, replayed catalog generations, downgrade,
offline cached operation, interrupted download and rollback. The resolver must
return either one verified eligible release or no release, with a diagnostic
reason suitable for HA; it must never return a merely newer SemVer.

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

## Legacy rollout ordering

Fresh radios can receive the verified baseline over USB. A deployed 0.18 radio
needs that same trusted baseline before it can accept signed-only OTA commands;
gateway 0.39 deliberately refuses to send those commands to legacy nodes.
Coordinate a legacy TLS bootstrap with the gateway/catalog cutover, or use USB.
Do not enable an unsigned bypass in the signed gateway.

The gateway handshake must recognize `firmware_signed_ota`, not merely verify
signatures later at the catalog boundary. An older gateway rejects a 0.19 hello
containing the new capability even when its token and TLS connection are valid.
Once the baseline image is staged, bring up the matching gateway and signed
catalog before judging candidate health. Repeated USB serial opens can reset
some ESP boards and consume their unconfirmed-boot allowance; keep one capture
connection open across a trial or observe it over the network.

For a mixed 0.18/0.19 fleet, a temporary migration artifact can backport only
the signed-capability hello allowlist entry to the existing 0.38 runtime. This
keeps already-updated owners authenticated while the remaining legacy nodes
receive the independently signature-verified baseline through their existing
TLS updater. This is a trusted bootstrap, not on-device signature enforcement
by 0.18. Restrict the temporary catalog to that approved image; preserve the
current database and configuration, and do not restore an older data backup.

Update one idle owner at a time and wait for `confirmed` /
`gateway_and_radio_healthy`, restored ACK assignments, and preserved valve
counter state before proceeding. Restore the current signed-only runtime and
catalog immediately afterward. Keep migration artifacts outside maintained
production source: this is not an unsigned OTA option in the released gateway.
Deployment qualification is recorded in `PROJECT_ROADMAP.md`.
