# Getting started with RainPoint Local

This guide is for early testers building their own ESP32/CC1101 radio nodes.
It describes the current source installation, not a released turnkey product.
Ask the maintainer for an agreed commit before testing; do not assume the latest
development branch is a qualified release. A local candidate bundle can now be
built with [the packaging guide](docs/ALPHA_BUNDLE.md); none is published yet,
and there is no hosted browser flasher. The live launch checklist is in the
[project roadmap](PROJECT_ROADMAP.md#alpha-cohort-preparation).

## What you are installing

There are three parts:

- **RainPoint Local Gateway app** (`rainpointd`): runs on Home Assistant OS and
  stores device associations, radio ownership and protocol state.
- **RainPoint Local integration** (`rainpoint_local`): provides HA devices,
  entities and setup screens. HACS installs this part, not the gateway app.
- **Custom radio node**: an ESP32 plus one CC1101, powered by USB and connected
  over Wi-Fi. It does not need to be attached to your HA machine.

The vendor's **stock RainPoint gateway**, vendor account and cloud integration
are not needed for local operation. An SDR is not needed either. This project
does not automatically import cloud devices, dashboards or automations.

The separate integration domain lets you retain the existing cloud integration
for other devices. That is software separation, **not RF coexistence validation**.
Do not command the same valve through both systems. Keep the stock RainPoint
gateway off during local pairing; plan a separate test window if it waters other
plants. Returning a device to the stock system may require vendor re-pairing.

## Before you begin

The alpha includes moisture sensors and both supported valve families. Valve
tests should initially use a dry valve
disconnected from the water supply. Do not replace essential irrigation before
you have verified reporting, actual open/stop behavior and failure feedback.
Keep a manual watering plan; stale or missing telemetry is not proof a valve
is closed. Battery replacement/rejoin and sustained stock/local coexistence
remain incompletely qualified.

Current transports assume a trusted LAN. Node authentication is implemented,
but traffic is not encrypted and firmware is not publisher-signed. The initial
Wi-Fi setup access point is open. Commission in a trusted location; never expose
ports to the Internet. Read [security boundaries](SECURITY.md) before enrolling.
An invited alpha still needs an explicit decision to accept these limitations;
this guide does not waive the publication security gates.

### Supported starting point

| Item | Requirement |
|---|---|
| HA installation | Home Assistant OS, aarch64 or amd64; declared minimum HA 2026.7.0 |
| Integration | HACS custom repository or manual custom-component install |
| ESP32 | Tested classic ESP-WROOM-32 development board, USB-C, `esp32dev` target; not an ESP32-C3/S3 substitute |
| Radio | One 433 MHz CC1101 module with the documented eight-pin connector and antenna |
| Power/wiring | USB supply, USB data cable for first flash, short jumpers/breadboard; 3.3 V radio power and logic |
| Network | 2.4 GHz Wi-Fi, preferably same LAN/subnet as HA with multicast discovery allowed |
| Computer | Git and PlatformIO Core 6.1.19 for the source-based USB flash |

Use the exact board's printed GPIO names, not physical header position. Board
width, pin count and USB connector alone do not identify a compatible pinout.
HA Container/Core users need a separately managed gateway; that path is outside
this first-test guide. Minimum versions are declarations, not a tested matrix
of every HA/OS/board combination.

### Device scope

| Model/family | What to expect | Important limit |
|---|---|---|
| HCS02x / HCS026FRF soil sensor | Local pairing, moisture, categorical battery, report freshness | Do not interpret battery as a measured percentage; validate your hardware revision |
| HTV405FRF four-zone valve | Local pairing and bounded 1–60 whole-minute controls | Supervised control option; battery not decoded; no water-volume capability |
| HTV145FRF single-zone valve | Local pairing path, qualified controls, duration, usage and categorical battery | Partial protocol association; new HA onboarding still needs physical acceptance; currently one single-zone valve per gateway identity and per node |

An illuminated pairing LED alone does not qualify valve controls. Unknown
models/frequencies are not supported merely because they look similar.

## 1. Select source and back up HA

Create a Home Assistant backup and retain it outside the HA machine. Obtain the
agreed revision from the maintainer, then clone this repository on your computer:

```sh
git clone https://github.com/fholgado/rainpoint-local.git
cd rainpoint-local
```

Check out that agreed revision before copying files or building. Use the same
revision for the app, integration and firmware unless its release notes specify
a compatible combination. The current documented baseline is gateway 0.37.1,
integration 0.17.0 and unified firmware 0.17.0; these are separate version numbers.

## 2. Install the gateway app

For a revision-pinned alpha, copy the checked-out `rainpointd_addon` directory
to HA's `/addons/rainpointd` using your normal HA file access method. The resulting
path must contain `/addons/rainpointd/config.yaml`, not an extra nested folder.
Reload the app store and install **RainPoint Local Gateway** from local apps.
Keep backups outside `/addons` and exclude macOS `._*` files.

The repository also has third-party app-store metadata. Adding
`https://github.com/fholgado/rainpoint-local` through the app store's repository
menu is the intended easier distribution path, but it follows published
repository state rather than the commit you selected locally. Fresh installation
through that route remains an alpha launch check. Follow HA's
[third-party repository instructions](https://www.home-assistant.io/common-tasks/os/#installing-a-third-party-app-repository).
Do not install both a local-source and repository copy of the gateway.

Start with these settings; enable the four-zone control option when testing
that valve as described below:

```yaml
transport: network
node_listen_port: 8790
supervised_htv405_control: false
htv145_dry_acceptance: false
```

Leave management/node credentials and the device catalog at their defaults;
do not copy another installation's tokens, database or device IDs. The gateway
generates a persistent local identity and manages credentials. Start the app
and enable start-on-boot. Its log should show network API and authenticated
node listeners, without repeated restarts. No USB SDR configuration is required.

The radio must reach HA TCP 8787 (API/firmware) and 8790 (node connection).
Keep the setup portal/adoption discovery reachable on the local LAN. Guest
network isolation or blocked multicast can prevent adoption even with good RSSI.

## 3. Install the HA integration

For HACS, add `https://github.com/fholgado/rainpoint-local` as a custom repository
of type **Integration**, then download **RainPoint Local** and restart HA.
See [HACS custom repositories](https://www.hacs.xyz/docs/faq/custom_repositories/).
If the maintainer-selected revision is not offered by HACS, use the manual path
instead; do not silently mix versions.

Manual path: copy `custom_components/rainpoint_local` to
`/config/custom_components/rainpoint_local`, then restart HA. Do not copy the
repository root or replace the existing cloud integration's directory.

In **Settings → Devices & services**, accept the discovered RainPoint Local
gateway. Supervisor discovery supplies its management credential privately.
If it is missing, check that both the app and custom integration are installed,
the app is running, and HA has restarted. Do not paste credentials from logs
or another installation to work around discovery.

## 4. Wire and flash one node

With power disconnected, follow the
[numbered wiring table](firmware/rainpoint_bridge/README.md#supported-hardware-and-wiring).
CC1101 VCC goes to **3V3, never 5 V**. GDO0 → GPIO26 is required. GDO2 is unused
by current firmware and can be left disconnected. Keep the antenna connected
and include local supply decoupling where practical.

Connect a USB **data** cable, then build:

```sh
pio run --project-dir firmware/rainpoint_bridge --environment rainpoint_bridge
pio device list
```

Identify the new ESP32's serial port. Upload using the following command,
replacing `YOUR_SERIAL_PORT` with that exact port:

```sh
pio run --project-dir firmware/rainpoint_bridge --environment rainpoint_bridge \
  --target upload --upload-port YOUR_SERIAL_PORT
```

Do not select a port belonging to another controller. PlatformIO handles the
bootloader, partition table and application; an OTA `firmware.bin` alone is not
a complete first-flash package. If connection fails, check the data cable and
hold BOOT while the uploader connects. Avoid erasing an already adopted node
unless deliberately resetting its configuration.

## 5. Join Wi-Fi and adopt in HA

1. Join **RainPoint Local Setup xxxxxx** from a phone or computer.
2. Open the captive setup page and enter your 2.4 GHz Wi-Fi credentials.
3. Return to the home network. In HA, accept the discovered radio node.
4. Give it a friendly name/area. Use **Identify**, then press ESP32 **BOOT** when
   prompted to confirm the physical node.
5. Wait for authenticated connection and healthy radio status. No ESP ID,
   RF endpoint or setup token is required in the normal flow.

You can now power it from a USB supply away from HA. Start with one node; add
coverage later. See [onboarding and placement](NODE_ONBOARDING.md). A powered
ESP32 with good Wi-Fi does not prove the CC1101 is wired correctly: confirm
radio health and actual sensor reports too.

## 6. Pair and verify your devices

The alpha covers all three supported families. Follow the sensor path below
for moisture sensors, or the valve path for a valve; owning a sensor is not a
prerequisite for valve testing.

### Moisture sensors

Turn off the stock RainPoint gateway for the agreed test window. Open
**RainPoint Local → Configure → Add a RainPoint device → Sensors**, select the
supported model and closest radio, then choose **Next** to review. **Back**
preserves the radio/window selection. **Start pairing** arms the radio; only
then perform the sensor's pairing gesture. Choose a long enough window to walk
to the sensor. Normal short presses are not the pairing gesture.

Wait for HA's outcome and a fresh moisture report. Compare it with the sensor
display, give the device a name/area, then confirm later reports arrive without
further button presses. Verify battery/freshness entities without assuming every
field is supported. Native HA menus provide Back actions, not footer Back/Next
buttons on every screen.

Pairing and removal instructions for existing devices are in
[node onboarding](NODE_ONBOARDING.md#pairing-devices-through-a-node). Removing a
device from HA does not prove the battery-powered device forgot its RF identity.
Do not remove an existing HA device merely to recover its association.

### Single-zone and four-zone valves

Choose **Add a RainPoint device → Valves**, select the exact model and closest
radio, and follow review → Start pairing before performing the valve's gesture.
Keep the stock gateway off during the exchange. Start dry. HTV405 actuation needs
the app's explicit `supervised_htv405_control` option. Do not enable unrelated
research options to bypass unavailable controls. HTV145 has a separate accepted
pairing and consented control-verification flow; it may request two one-minute
runs. Read the [verification behavior](NODE_ONBOARDING.md#pairing-devices-through-a-node)
before consenting. New UI onboarding is not yet physically qualified end to end.

Check the valve's actual open, automatic stop and early-stop behavior against HA.
After these checks pass, supervised live irrigation is within the alpha scope;
remain available to inspect the valve and water manually if necessary. Do not
copy the household dashboard or
automations under `examples/federico-garden`: their entities, schedules and
fallback policies are installation-specific, not an automatically installed
notification/watchdog package for your garden.

## Updates, recovery and feedback

The gateway app, integration and firmware update independently. Follow the
maintainer's tested version combination; back up first and update while valves
are idle. Compatible radio updates appear in HA **only after** a firmware catalog
and matching artifact have been staged on that installation. HACS does not
provide radio firmware updates. Catalog staging currently requires maintainer
or command-line work; an empty list is not evidence of a broken radio.

Keep a known-good source revision and first-flash artifacts. Interrupted OTA
should retain the running image; a candidate must verify integrity and boot
health. Do not factory-reset as the first response to a missed report. Holding
BOOT for ten seconds clears Wi-Fi/adoption state, not the separate sensor/valve's
memory. See the [firmware recovery guide](firmware/rainpoint_bridge/README.md#usb-recovery).

When reporting an issue, include model/revision, ESP32/CC1101 type, app/integration/
firmware versions, exact local time **and timezone**, action, expected/observed
behavior, Wi-Fi RSSI and radio/report diagnostics. State whether the stock
gateway was on and whether the valve was dry. Review logs before sharing:
exclude Wi-Fi passwords, bearer/node tokens, HA backups/databases and unrelated
device information. File issues in the
[project tracker](https://github.com/fholgado/rainpoint-local/issues).

If a valve's physical state is uncertain, inspect it or shut off its water
supply; do not interpret a failed UI request as proof that nothing opened.
