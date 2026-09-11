# Alpha bundle: flashing, updating and rollback

This bundle is an **unpublished candidate**, not evidence that physical release
gates passed. Read `compatibility.json` for the exact source commit and three
component versions. A bundle marked `source_dirty: true` is a developer preview
and must not be distributed. The maintainer must explicitly approve a release.

## Verify before use

Extract into a new directory. On macOS run `shasum -a 256 -c SHA256SUMS`; on
Linux run `sha256sum -c SHA256SUMS`. All entries must pass. Obtain the bundle
from the maintainer's agreed channel; checksums detect corruption, not a
malicious replacement of both files and checksums. Publisher signing is not
implemented. Never mix USB parts from different bundles.

`rainpoint-source.tar.gz` contains the gateway app under `addons/rainpointd`
and the separate HA integration under `custom_components/rainpoint_local`.
Extract to a temporary directory, inspect, then use the getting-started guide.
It is not a Home Assistant backup: do not use Restore backup to install it.

## First USB flash: new classic ESP32 only

Use the classic 4 MB ESP32 `esp32dev` hardware and documented CC1101 wiring.
Disconnect the radio's power before adjusting wires; attach its antenna before
operation. Identify the correct USB data port. This first-flash procedure writes
bootloader, partition table and OTA selection metadata; **do not use it for
routine updates of an adopted node**. It can reset OTA selection and change
the partition layout. It does not transfer another installation's credentials.

PlatformIO source upload remains the supported tool-managed alternative. For
these prebuilt images, use Espressif esptool 4.11.0 in a separate Python virtual
environment. From the extracted bundle directory, replace `YOUR_SERIAL_PORT`:

```sh
python -m esptool --chip esp32 --port YOUR_SERIAL_PORT --baud 460800 \
  --before default_reset --after hard_reset write_flash -z \
  --flash_mode dio --flash_freq 40m --flash_size 4MB \
  0x1000 usb/bootloader.bin 0x8000 usb/partitions.bin \
  0xe000 usb/boot_app0.bin 0x10000 usb/firmware.bin
```

The packager checks these offsets against the build receipt and actual OTA
partition table; a different profile is rejected, not guessed. `usb/manifest.json`
also records the layout; there is not yet a hosted browser flasher. After flashing,
follow Wi-Fi setup, BOOT adoption and sensor/valve pairing in `GETTING_STARTED.md`.
No serial port is opened by the packaging or verification commands themselves.

## OTA for an already adopted node

### One-time plaintext-to-TLS cutover

The current candidate requires matching TLS-capable gateway, integration and
radio firmware. This migration is **not** the routine rolling update described
below. Qualify on a spare node first. Back up the gateway database and credentials
before schema 25 is opened; an old gateway requires restoring that backup.

For an approved live cutover, keep valves idle and preserve the old working
gateway while delivering the candidate images through the old OTA mechanism.
Updated nodes cannot reconnect to that plaintext gateway. Then update the
gateway and HA integration together, and verify every node reconnects over TLS,
restores ACK ownership and retains counters. Avoid repeated node power cycles
while awaiting the new gateway: three unconfirmed boots trigger rollback.
If that outage is unsuitable, use USB on a spare node for qualification and
schedule the live cutover separately. Do not enable plaintext fallback.

Initial adoption remains trusted-network-only. Operational API callers now need
a TLS credential; older HTTP-only research scripts cannot access the new listener.

### Routine updates after all components support TLS

First back up the HA gateway app and retain the previous bundle/catalog.
Use the version combination in `compatibility.json`, update while valves are
idle, and update one radio at a time. Copy the **contents** of `ota/` to
`/share/rainpoint-local/firmware/` on HA: the `catalog.json` and the `.bin` it
references must remain together. Keep the app's `firmware_catalog_path` pointed
to that catalog, then restart the gateway app while idle to load it.

For a fresh catalog this is a direct copy. If a catalog already exists, back it
up and merge offers with `tools/stage_firmware_release.py` from the matching
source checkout rather than discarding rollback offers. That tool requires an
explicit release ID, version, summary, notes and `--firmware-variant unified`;
use the values in the bundled catalog. Never mix research firmware variants.

The compatible release should appear in the radio's HA Update entity. Select
Install and wait for the new version plus healthy-boot confirmation; receiving
the bytes alone is not success. Same-version candidates are not an update path:
bump the firmware version when distributing changed firmware. If an update
fails, retain the currently running image and report the error. Do not repeatedly
reset a node or erase its credentials to force an offer.

## Recovery

After a failed download, the previous running image should remain intact.
An unconfirmed candidate has rollback protection; preserve its diagnostic
reason and check Wi-Fi/radio wiring before retrying. For a healthy but unwanted
version, ask the maintainer for a supported rollback procedure—the UI does not
promise arbitrary downgrade offers. A manual USB recovery requires identifying
the installed partition layout and preserving or deliberately resetting node
adoption; the first-flash command above is not a blanket rollback command.

Restore gateway app data together with its compatible source version from your
own backup when needed. Keep the same logical gateway identity and association
database. Restoring software cannot undo a device's RF re-pairing. Check physical
valve state before restoring operation; never rely on a stale dashboard alone.

## Maintainer preparation (source checkout)

```sh
pio run --project-dir firmware/rainpoint_bridge --environment rainpoint_bridge \
  --target release_receipt
python tools/package_alpha.py /tmp/rainpoint-alpha-candidate.zip
```

Commit source first. The tool refuses dirty source, a receipt from a different
commit, changed/missing images, mismatched versions and unsupported layouts.
It checks production firmware boundaries and runs the isolated source-install
smoke test. It creates no tag/release, flashes nothing and contacts no radio.
The output is deterministic for identical source and build inputs; this does not
claim compiler output is reproducible across arbitrary toolchains/hosts.

The live launch checklist is `PROJECT_ROADMAP.md`; clean HA OS/HACS discovery,
new physical adoption and sensor/valve field acceptance remain distinct from
this automated package smoke test.
