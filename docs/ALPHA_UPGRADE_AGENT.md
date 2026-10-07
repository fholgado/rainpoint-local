# Agent alpha upgrade procedure

Use this procedure when updating an existing RainPoint Local installation.
Perform the software work through authorized HA access; ask the user for
physical checks or credentials only when needed. Give them the
[user upgrade guide](ALPHA_UPGRADE.md). Release creation follows the separate
[release playbook](RELEASE_PLAYBOOK.md).

## 1 Identify the upgrade

Read the target release notes, currently [Alpha 2](ALPHA_2.md), and its
`compatibility.json`. Record installed and target gateway, integration and
per-radio firmware versions, hardware, assigned devices and update scope.
Version numbers are independent; HACS installs only the integration.

For signed, TLS-capable radios, continue below. Alpha 1 to Alpha 2 uses this
routine path. For older plaintext/pre-signing radios, use the
[transport migration and signed baseline procedures](ALPHA_BUNDLE.md#ota-for-an-already-adopted-node).
For experimental builds, check their matched compatibility and signing profile
before choosing an offer; a trial's larger-looking version is not proof of
public-release compatibility. A new board follows [Getting started](../GETTING_STARTED.md).

**Done when:** every authorized target has an identified upgrade path and
compatible version combination.

## 2 Prepare the installation and assets

Wait for watering to finish. Take an HA backup including gateway app data and
retain the existing firmware catalog. Preserve gateway identity, credentials,
associations, counters and HA entity IDs; update the existing installation.

Download the target radio ZIP, matched source archive, compatibility metadata
and `SHA256SUMS` from the published release. Verify downloaded assets, then
extract into a new directory and verify the ZIP's internal checksums too:

```sh
# macOS; use sha256sum on Linux
shasum -a 256 -c SHA256SUMS
```

Use the published signed image without rebuilding it. From the repository at
the release's source tag, use `tools/sign_firmware.py verify` with the image,
envelope, key ID and repository-pinned public key; read its `--help` for inputs.
Compare the envelope's version/source/hash/size with `compatibility.json` and
the application entry in `usb/build-receipt.json`. The runtime-only source
archive omits `tools/`; use the tagged repository for these verification and
staging tools. See [bundle verification](ALPHA_BUNDLE.md#verify-before-use) and
[signature details](FIRMWARE_SIGNING_DESIGN.md#verification-and-trust-provisioning).

**Done when:** the backup and previous catalog are available, and downloaded
assets match the target release, checksums and signed firmware identity.

## 3 Update the gateway and integration

Update the gateway through HA's app/add-on store and confirm the required
version is actually running **before updating any radio**. For Alpha 2,
gateway **0.39.19** must precede firmware **0.21.0**: 0.39.18 can deliver it but
rejects its new shared-radio capability on reconnect. Hardware compatibility
in an OTA catalog does not establish gateway compatibility.

Keep components already at the target version; verify them without reinstalling.

Update the integration through HACS using the integration release in the notes,
enabling prereleases if necessary, then restart HA. If either store lacks the
required version, use the matched archive's `addons/rainpointd` or
`custom_components/rainpoint_local` following the
[pinned source installation](ALPHA_BUNDLE.md#verify-before-use). Keep source
backups outside HA's `/addons` children. Retain one gateway and the existing
integration entry rather than creating replacements.

**Done when:** the target gateway is running, the target integration is loaded,
and the existing radios/devices remain registered.

## 4 Stage the signed radio offer

Firmware offers are local catalog entries, not automatic GitHub discovery.
For a fresh catalog, copy the radio ZIP's `ota/` contents to
`/share/rainpoint-local/firmware/` on HA. For an existing catalog, merge the
offer with `tools/stage_firmware_release.py` from the matching release source.
Read its `--help`; take the image, release ID, version, summary, notes and
compatible variants from the bundled catalog and use its
`--firmware-variant unified` and `--signature firmware-signature.json`.
Preserve previous offers; stage the referenced binary before replacing the
catalog. Follow [OTA staging details](ALPHA_BUNDLE.md#routine-updates-after-all-components-support-tls-and-signed-ota).

Confirm the gateway's `firmware_catalog_path`, restart it while idle to load the
offer, and inspect the selected radio's Update entity. An unsigned preview or
development signature is not a public production offer.

**Done when:** each authorized radio needing an update has the intended signed,
compatible offer and the prior catalog entries remain available.

## 5 Update and verify each radio

Install through the selected radio's HA Update entity, one radio at a time.
Skip radios already on the target version. Wait for the actual running version,
authenticated reconnection, healthy OTA confirmation and restored device
ownership before advancing. Check update detail/candidate state and gateway
logs if confirmation is missing; receiving the bytes alone is not success.

Keep working associations and saved counters. Do not use a complete first-USB
layout over an adopted node for routine updates. If OTA fails, preserve its
diagnostic reason and running image; diagnose before retrying. For recovery or
downgrade, follow [bundle recovery](ALPHA_BUNDLE.md#recovery) rather than erasing
credentials or forcing counters.

**Done when:** every authorized radio is healthy on its target version, with
its prior assignments intact, or an unresolved target is explicitly reported.

## 6 Check operation and hand off

Compare device/entity assignments with the initial inventory. Check fresh sensor
report timestamps as they arrive and valve readiness without issuing commands.
If a short watering check is authorized, use a dry valve or have the user
visually confirm actual opening/closing; verify HA watering and closed/ready
states and default notifications. For a newly added HTV213, use the
[two-zone pairing and short tests](TWO_ZONE_ALPHA_TESTING.md).

Report installed versions per component/radio, completed and skipped targets,
backup location, checks performed and unresolved errors. Distinguish software
health from physical watering confirmation. Existing working devices do not
need re-pairing or a new soak simply because software changed.

**Done when:** the user has the upgrade result and any specific follow-up,
without implying unperformed device tests passed.
