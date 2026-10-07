# Upgrade an alpha installation

Use this guide to update an existing RainPoint Local installation. Your paired
devices, names and automations should stay in place; a software update does not
require re-pairing. For a first installation, use [Getting started](../GETTING_STARTED.md).

The current release is [Alpha 2](ALPHA_2.md). Its release notes list the three
matched versions and downloads: gateway, HA integration and radio firmware.
They update separately. Give your agent the
[agent upgrade procedure](ALPHA_UPGRADE_AGENT.md) to handle downloads, firmware
staging and verification for you.

## Before updating

Let watering finish and arrange a short maintenance window. Take a Home
Assistant backup that includes the RainPoint Local Gateway app data, or have
your agent do it. Leave your working devices paired and radios powered.

## Update in this order

1. **Gateway first.** Open RainPoint Local Gateway in HA's app/add-on area,
   install the required update and confirm it is running. For Alpha 2 this must
   be **0.39.19 before firmware 0.21.0**; an older gateway can transfer the image
   but reject the radio when it reconnects.
2. **HA integration.** In HACS, select the RainPoint Local integration release
   named in the release notes, enabling prereleases if needed. Restart Home
   Assistant when prompted. A `firmware-...` release is for radios, not HACS.
3. **Radios one at a time.** Have your agent stage the signed firmware offer.
   Open the radio device under **Settings → Devices & services → RainPoint
   Local**, select its firmware Update entity and install the offered version.
   Wait until it reconnects on the new version and is healthy before updating
   the next radio. HACS does not update radios.

Already on one of the target versions? Keep it and update only the components
that still need changing, in the same order. If the app store does not offer the
required gateway version, ask your agent to use the matched source installation.

## Check afterward

Confirm the same devices and controls remain in HA, radios are connected, and
sensor readings receive fresh timestamps as reports arrive. Old readings may
remain visible during the update; a visible value alone is not a fresh report.

For valves, use a dry valve or visually confirm opening and closing during a
short run or your next planned watering. HA should show watering and then
closed/ready. Built-in watering notifications are enabled by default; phone
forwarding remains optional. Software updates alone need no new pairing tests
or multi-day wait.

## If something goes wrong

- **No firmware offer:** ask your agent to check the signed catalog and gateway
  compatibility. Offers are staged by an agent/maintainer, not fetched
  automatically from GitHub.
- **Radio disconnected after an update:** check the running gateway version
  and Wi-Fi first. Keep its pairing and credentials intact.
- **Update failed or rolled back:** keep the error and ask your agent to diagnose
  it before trying again. USB first-flash instructions are not a routine update
  or downgrade procedure.

Use [GitHub issues](https://github.com/fholgado/rainpoint-local/issues/new/choose)
for help. Include the alpha label, all three installed versions, affected
device/radio model, timestamp and error; remove credentials from logs.
