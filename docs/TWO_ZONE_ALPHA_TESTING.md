# Two zone alpha update and testing

Give this guide to the agent updating an existing RainPoint Local installation
for an **HTV213FRF** two-zone valve. The agent handles software updates and
checks; the user handles the valve button, batteries and visual confirmation.

Use [firmware 0.21.0](https://github.com/fholgado/rainpoint-local/releases/tag/firmware-v0.21.0)
with **gateway 0.39.19** and **integration 0.18.6**: the current
[Alpha 2 stack](ALPHA_2.md). Alpha 1 remains an archived baseline. Other two-zone
models are not qualified by this release.

## Agent update the existing installation

Follow the [agent alpha upgrade procedure](ALPHA_UPGRADE_AGENT.md) for version
inventory, verified assets, gateway-first updates, signed OTA staging and
per-radio confirmation. Give the user the [upgrade guide](ALPHA_UPGRADE.md).
Keep working associations; proceed below only for new two-zone pairing or
agreed control checks. New boards use [Getting started](../GETTING_STARTED.md).

## Agent check two zone radio readiness

Firmware **0.21.0** supports sensors and valves on the same radio, including
up to **eight HTV213 associations** per radio. Keep working sensor associations;
there is no dedicated-radio requirement or manual tuning prerequisite.
Check that the updated radio is connected and selectable in HA before asking
the user to press the valve button. Older radio firmware needs updating to use
shared ownership.

The default carriers were tested on two radios. Existing overrides remain
effective; unusual hardware can use the optional authenticated
`POST /api/v1/nodes/{node_id}/htv213-calibration` with integer-Hz
`initial_center_hz` and `routine_center_hz`. This changes the recipe for future
enrollment, not a working valve's saved association. Use RF diagnostics if
tuning is needed, not repeated pairing or forced counters.

## User pair the valve

Turn off the stock RainPoint gateway. Test with the valve disconnected from
water, or visually check that each outlet really opens and closes.

In HA, open **Settings → Devices & services → RainPoint Local → Configure →
Add a RainPoint device → Valves → HTV213FRF**. Select the compatible radio, review
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

For a shared radio, also confirm its existing sensors continue updating before
and after valve control. Pairing the valve should not require re-pairing sensors
or change another valve's association. Report any stale readings or wrong-target
behavior alongside the valve results.

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
