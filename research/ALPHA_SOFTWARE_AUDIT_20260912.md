# Alpha software audit — 2026-09-12

Scope: the supported HCS026, HTV145 and HTV405 paths, release packages, and
production/research interfaces. This is evidence, not another checklist; see
[the roadmap](../PROJECT_ROADMAP.md) for acceptance and physical tests.

## Discovery and capability decisions

- `product_identity.py` distinguishes family, exact RF model, trusted registry
  metadata, and conflicting identifiers. Product `0x48` alone does not prove an
  HCS026 retail model. Unknown model codes remain generic.
- `device_catalog.py` resolves normalized endpoints and endpoint pairs to stable
  IDs. Display names do not select a decoder, route, zone count, or TX owner.
- `Gateway.pairing()` advertises three supported profiles; HA parses their typed
  metadata and filters radio capabilities. A fresh persistent gateway advertises
  these profiles without creating devices or inventing a household installation.
- HTV405 identification currently uses its validated frame/profile signature,
  not an invented retail model-code mapping. A shared valve product family is
  not permission to apply four-zone commands to an unknown valve.
- HA's explicit model-specific topology is intentional: four zones only for
  HTV405, no water-usage entity for it, and no phantom zones for HTV145. Adding
  a new model still requires a validated protocol/profile and field support.

`tests/test_discovery_contract.py` exercises the actual gateway catalog through
HA's parser, unknown/conflicting family evidence, arbitrary names and endpoints.
Existing RF tests cover compact-report canonicalization, integrity, suppression,
and persistence of product evidence. This is not qualification of other models.

## Module interfaces and retained research

| Interface | Current contract |
|---|---|
| RF → ingestion | `RFObservation` carries decoded fields, timestamp and receiver metadata; decoders remain transport-independent. Field dictionaries accommodate packet families. |
| Receiver → gateway | Node protocols 1/2 are explicitly negotiated. V1 is receive-only; V2 requires node/gateway authentication and supported capabilities. Production transport uses TLS-PSK. |
| Gateway → HA | `/api/v1`; HA checks version, stable gateway identity, capability metadata, profile shape and event cursors. Unknown state-changing events request an authoritative snapshot. |
| Persistence | SQLite schema 25 and HA config version 3 have migration tests; associations and counters survive independently of UI labels. |
| Research → production | Research imports runtime decoders, never the reverse. Installable source contains only the app and integration, not captures, fixtures, development tools or household examples. |

Keep these existing seams. Do not introduce a second protocol implementation
or replace flexible packet fields with a speculative all-model schema merely
for this audit. Contracts are enforced by `test_api_models`, `test_esp32_network`,
`test_addon_boundaries`, migration tests and the actual-Core qualification tool.

The firmware-image checker now always requires both valve families, instead of
requiring callers to opt into three retired build distinctions. This changes
validation tooling, not firmware or RF commands. Captured pairing fixtures and
the opt-in `/research/htv145-acceptance/` diagnostics remain: terminal enrollment
and independent ACK timing are still open physical tests. The app's normal
configuration and HA integration do not enable that research endpoint.

Research should remain in this repository during alpha: shared, redacted
fixtures currently verify the frozen pairing prefixes in CI. A separate repo
would require a versioned fixture/import contract and a coordinated release
process. That choice remains for the user before stable release; no repository
split or HomGar integration work was performed.

## Public artifacts

The published Alpha 1 source tarball and USB/OTA zip passed
`tools/check_public_artifact.py`. It checks archive paths/types/duplicates,
bounded sizes, private/generated filenames, complete PEM private keys and
recognizable GitHub credentials without printing matched contents. Public signing
keys are expected. Crypto-library PEM delimiter strings inside firmware are
not themselves private keys; a regression covers this distinction.

CI repeats the check for generated source and radio packages. This complements
the source allowlist, runtime household/research-import exclusions, checksum and
publisher-signature verification; it is not a complete secret scanner or an
audit of Git history. Published Alpha 1 bytes were not changed.

Corrected stale app/firmware instructions about manual setup codes, beta-only
controls, deferred valve-registry migration and the firmware version. Normal
setup remains discovery plus physical confirmation, with one unified image.

## HA registry compatibility

HA 2026.8 made identifiers entry-scoped and deprecated unscoped lookups until
2027.8 ([official migration notice](https://developers.home-assistant.io/blog/2026/07/21/device-registry-single-config-entry/)).
The three metadata/re-pair call sites now use the owning entry through one
compatibility helper. Only HA 2026.7 uses the old method, with an ownership check.
Unit tests distinguish two gateway entries sharing an identifier; actual-Core CI
exercises lookup/removal on both supported test versions and forbids deprecated
lookup calls on the modern path. No live registry or RF association is changed.

## Mac receiver verification

The new research runner passed tests using real child processes and the actual
gateway's TLS-PSK receiver. Tests cover bounded storage across restart, child
termination, explicit UTC receipt/verbatim source time, receive-only capability
negotiation, forwarding failure/drop behavior, and visible decoder failure.
The receive-only USB preflight on Sep 12 reported `No supported devices found`
(decoder exit 2); no RF reception or launchd qualification is claimed. No
background job, gateway credential or live forwarding route was installed.
