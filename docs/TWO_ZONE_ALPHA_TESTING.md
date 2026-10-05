# Two zone alpha update and testing

Give this guide to the agent updating an existing RainPoint Local installation
for an **HTV213FRF** two-zone valve. The agent handles software updates and
checks; the user handles the valve button, batteries and visual confirmation.

Use [firmware 0.20.0](https://github.com/fholgado/rainpoint-local/releases/tag/firmware-v0.20.0)
with **gateway 0.39.18** and **integration 0.18.5**. This is a firmware alpha,
not a replacement for the pinned [Alpha 1](ALPHA_1.md) stack. Other two-zone
models are not qualified by this release.

## Agent update the existing installation

1. Record installed versions, radio hardware and existing device assignments.
   Confirm a classic ESP32/CC1101 node and wait until all watering is finished.
   Take an HA backup including the gateway data and retain the existing catalog.
   Preserve credentials, gateway identity, associations and counters.
2. Download `rainpoint-radio-0.20.0.zip`, `rainpoint-source.tar.gz`,
   `compatibility.json` and `SHA256SUMS` from the release. Check the downloaded
   assets against `SHA256SUMS`, then extract the radio ZIP and verify its internal
   checksums too (`shasum -a 256 -c SHA256SUMS` on macOS). Do not rebuild the
   signed application or select `firmware-v0.20.0` as an integration in HACS.
3. Update the existing gateway through HA's app store to **0.39.18**. Use HACS
   for integration **0.18.5** if offered. Otherwise use the release's matched
   source archive: copy its `custom_components/rainpoint_local` into HA's
   configuration directory after backing up the old component, then restart HA.
   The archive also contains `addons/rainpointd` for a pinned local gateway
   install when the app store does not offer the required version. Update the
   existing installation; do not start a second gateway. See the
   [source installation details](ALPHA_BUNDLE.md#verify-before-use).
4. Stage the radio ZIP's `ota/` files under
   `/share/rainpoint-local/firmware/` on HA. With an existing catalog, merge the
   new offer using `tools/stage_firmware_release.py` from the
   [signed source tag](https://github.com/fholgado/rainpoint-local/tree/firmware-v0.20.0):
   use the bundled release ID/version, `--firmware-variant unified` and
   `--signature firmware-signature.json`. Keep previous offers and copy the
   referenced `.bin` before replacing `catalog.json`. Check the gateway's
   `firmware_catalog_path` points there, then restart the gateway while idle.
5. Install **0.20.0** through the selected radio's HA Update entity. Update one
   radio at a time. Confirm the new version, authenticated connection, healthy
   OTA confirmation and restored device ownership. A completed download alone
   is not success. Existing working associations do not need re-pairing.

For a new board only, use the ZIP's first-USB-flash instructions and normal
Wi-Fi/adoption flow. Do not write its complete USB layout over an adopted node
as a routine update. Older plaintext or pre-signing firmware needs the
[migration procedure](ALPHA_BUNDLE.md#ota-for-an-already-adopted-node), not this
routine OTA path.

## Agent check two zone radio readiness

This alpha needs **one dedicated radio per HTV213 valve**, with no other device
assignments and a saved carrier calibration for that physical radio. Firmware
0.20.0 supplies the required normal pairing/control capabilities. Check HA's
radio selection before asking the user to press the valve button.

If HA reports no prepared two-zone radio, check connection, firmware, existing
assignments and calibration. Updating firmware does not create calibration.
An uncalibrated radio needs maintainer-assisted measurement/provisioning before
pairing; independent second-radio calibration is still alpha test work. Do not
copy another radio's frequency correction or reset a working association.
The authenticated provisioning API is
`POST /api/v1/nodes/{node_id}/htv213-calibration`, with measured integer-Hz
`initial_center_hz` and `routine_center_hz`; it saves the profile without pairing
or watering. See the [carrier definition](../protocol_documentation/htv213frf.md#local-dry-test-candidate).

## User pair the valve

Turn off the stock RainPoint gateway. Test with the valve disconnected from
water, or visually check that each outlet really opens and closes.

In HA, open **Settings → Devices & services → RainPoint Local → Configure →
Add a RainPoint device → Valves → HTV213FRF**. Select the prepared radio, review
and start pairing **before** performing the valve's long-press pairing gesture.
The valve's success indication is only the first step: HA may wait up to ten
minutes for its later confirmation report. Leave the radio powered and finish
naming/saving when HA completes. Expect **one device with two outlet controls**,
not two valve devices. A timeout needs diagnostics, not repeated button presses.

## Run the short tests

Agent: use the actual entities on the saved device, not guessed entity IDs.
Get the user's agreement before starting water; stop the sequence if a result
is uncertain. Allow the preceding transaction to finish before the next run.

1. Set outlet 1 to **1 minute** and start it once. Confirm outlet 1 opens,
   outlet 2 stays closed, and outlet 1 stops automatically. HA should show
   watering during the run and return to closed/ready after completion.
2. Repeat the **1-minute** test on outlet 2. Outlet 1 must remain closed.
3. Set outlet 1 to **2 minutes**, start once and press Stop after about
   **15 seconds**. Confirm it closes early and HA returns to closed/ready.
4. While both are idle, restart only the test radio. Confirm it reconnects and
   the same two-outlet device remains usable without re-pairing. Try one more
   **1-minute** run on either outlet.

HA's built-in watering/problem notifications should appear by default. Phone
forwarding is optional. Completion can lag the physical stop while a final
valve report arrives; record the delay rather than send duplicate starts.
These first tests need no two-experiment unlock or 72-hour wait.

Optional next session: with both outlets idle and the radio left powered, remove
and reinsert only the valve batteries. Wait for fresh reports and try one
**1-minute** run without pairing or resetting counters. Report recovery success
or failure. Leave simultaneous outlet operation and stock-hub coexistence for
separate tests. Battery percentage and water-volume scaling are not qualified.

## Send the results

Report successes and failures in [GitHub issues](https://github.com/fholgado/rainpoint-local/issues/new/choose).
Include all three versions, valve model, ESP32/CC1101 type, timezone/timestamps,
which outlet/duration, actual opening/closing, HA states/errors, Wi-Fi RSSI,
stock gateway power state and whether the valve was dry. Attach relevant
diagnostics or logs with credentials and personal identifiers removed. Keep
the first failed attempt's evidence; do not force counters or replay an
unconfirmed command to make the test appear successful.
