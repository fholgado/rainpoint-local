# Getting started: agent-assisted setup

Give this guide to the agent helping you set up RainPoint
Local. The agent installs the software, flashes the firmware and checks the
connection. You assemble the radio, enter Wi-Fi details, press its confirmation
button and pair your devices through Home Assistant.

This alpha supports HCS02x/HCS026FRF moisture sensors, HTV145FRF single-zone
valves and HTV405FRF four-zone valves. A stock RainPoint gateway, cloud account
and SDR are not required. Cloud-device migration is not automatic.

## 1. Agent: confirm the setup

Ask for the user's HA address, device models and available hardware:

- Home Assistant OS on aarch64 or amd64, HA 2026.7.0 or newer, with HACS installed.
- A classic ESP-WROOM-32 development board (`esp32dev`, not C3/S3), one 433 MHz
  CC1101 with antenna, jumper wires, USB data cable and USB power supply.
- 2.4 GHz Wi-Fi reachable from HA, preferably on the same subnet.
- A computer with USB access to the board for its first flash.

Use authorized HA/browser access to do the installation. Ask the user only for
actions requiring their credentials, physical input or access you do not have.
Take an HA backup first.

Use [Alpha 1](docs/ALPHA_1.md): gateway **0.39.0**, integration **0.18.0** and
signed firmware **0.19.0**. Record all three installed versions. The release tag
is **`v0.18.0-alpha.1`**; component version numbers remain independent.
The app repository follows `main`, so check its offered gateway version against
this combination before installing. For a pinned source install, use the source
package on the release and the [bundle guide](docs/ALPHA_BUNDLE.md).

### Quick BOM (per radio node)

| Part | Quantity needed | Amazon US link / what to select |
|---|---:|---|
| ESP32 development board | 1 | [ELEGOO ESP-WROOM-32 USB-C, 3-pack](https://www.amazon.com/dp/B0D8T53CQ5). This is the board used in our reference build: classic ESP32, 30 pins, pre-soldered headers. Not ESP32-C3/S3. |
| CC1101 radio with antenna | 1 | [CC1101 with SMA antenna, 2-pack](https://www.amazon.com/dp/B01DS1WUEQ). Choose a **433 MHz module and matching antenna**, with the 2×4, 2.54 mm male header used in our wiring guide. |
| Short female-to-female Dupont jumpers | 7 wires | [EDGELEC 10 cm female/female, 120-pack](https://www.amazon.com/dp/B07GD312VG). Select **10 cm / 3.9 inch**, **female-to-female**, **2.54 mm**, individually separable connectors. GDO2 is unused, so an eighth wire is unnecessary. |

Also have a USB data cable for flashing and a USB power supply for deployment.
The ESP32's **3.3 V** output powers the radio; a breadboard or carrier PCB is
not required for this jumper-wire build. A 100 nF bypass capacitor at the radio
is recommended when practical; see the
[wiring guide](firmware/rainpoint_bridge/README.md#supported-hardware-and-wiring).

Links checked September 12, 2026; pack sizes, sellers and availability may change.
The radio and jumper links are sourcing examples, not separately qualified
supplier batches. Before buying, match the radio pin labels to the wiring table;
a listing advertising several bands does not guarantee a 433 MHz antenna.

## 2. Agent: install the gateway and integration

These are separate installs, both using repository-based UI paths:

| Component | Install through | Purpose |
|---|---|---|
| RainPoint Local Gateway (`rainpointd`) | HA app/add-on store | Stores associations and manages radios/protocol |
| RainPoint Local (`rainpoint_local`) | HACS, type **Integration** | Provides HA entities and pairing screens |

### Gateway app

[Add the RainPoint Local app repository to HA](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Ffholgado%2Frainpoint-local),
or open the app/add-on store's **Repositories** menu and add:

```text
https://github.com/fholgado/rainpoint-local
```

Install **RainPoint Local Gateway**. Keep `transport: network`, default ports and
automatically managed credentials. Supported valve controls are available
after normal pairing and owner setup; no research switches are required.
Start the app and enable start-on-boot.

### HA integration

In HACS, add the same URL under **Custom repositories**, choose **Integration**,
and download **RainPoint Local**, selecting **`v0.18.0-alpha.1`** in the version
selector (enable prereleases if necessary). Do not select the firmware-only
`firmware-v0.19.0` tag or `main` for a pinned Alpha 1 installation.
Arrange the HA restart with the user, then
accept the discovered gateway in **Settings → Devices & services**.

HACS installs the integration, not the gateway app or radio firmware. The app
repository removes manual gateway file copying. Repository metadata and CI
validation are present; testers are invited to report their fresh-install
results against the [alpha acceptance work](PROJECT_ROADMAP.md#alpha-cohort-preparation).
See [distribution details](docs/HACS_DISTRIBUTION_REQUIREMENTS.md) if installation
or version selection differs from this path.

**Done when:** the gateway stays running and the integration is loaded.
Discovery supplies credentials automatically; if it is missing, check app logs
and the HA restart.

## 3. Agent + user: wire and flash

Have the user wire the unpowered board using the
[numbered wiring table](firmware/rainpoint_bridge/README.md#supported-hardware-and-wiring).
CC1101 power is **3.3 V, not 5 V**. GDO0 is required; GDO2 is unused and optional.
Ask them to attach the antenna and connect the ESP32 by USB.

For Alpha 1, download **`rainpoint-radio-0.19.0.zip`** from the
[release](https://github.com/fholgado/rainpoint-local/releases/tag/v0.18.0-alpha.1),
verify its checksums and follow the included README's first-USB-flash command.
This uses the approved signed build without compiling it again.

Alternatively, to build from source, obtain the selected release tag and install
PlatformIO Core 6.1.19 if needed. From the checkout, run:

```sh
pio run --project-dir firmware/rainpoint_bridge --environment rainpoint_bridge
pio device list
```

Identify the connected ESP32's port, substitute it for `YOUR_SERIAL_PORT`, and
upload. Run these commands yourself when you have access; otherwise guide the user.

```sh
pio run --project-dir firmware/rainpoint_bridge --environment rainpoint_bridge \
  --target upload --upload-port YOUR_SERIAL_PORT
```

**Done when:** upload succeeds and the node boots. If upload cannot connect,
check the data cable and ask the user to hold BOOT during connection.
Source-built images are for USB flashing, not publisher-signed OTA distribution.

## 4. Agent + user: connect Wi-Fi and adopt

1. Ask the user to join **RainPoint Local Setup xxxxxx**, open its setup page
   and enter their 2.4 GHz Wi-Fi details.
2. Once they return to the home network, open the discovered radio in HA and
   give it a friendly name and area.
3. Use **Identify** if needed; ask them to press ESP32 **BOOT** when prompted.
4. Verify adoption completes, the node authenticates and CC1101 health is good.
   No pasted ESP IDs or setup tokens are needed.

**Done when:** HA shows a connected, healthy radio. The user can move it near
the garden and power it from USB; verify it reconnects there. Repeat for
additional nodes. See [node onboarding](NODE_ONBOARDING.md) for troubleshooting.

## 5. User: pair devices in HA

Once the app, integration and radio are ready, hand the user these instructions:

1. Temporarily turn off the **stock RainPoint gateway** for pairing.
2. Open **RainPoint Local → Configure → Add a RainPoint device**.
3. Choose **Sensors** or **Valves**, the model and the closest radio.
4. Select **Next**, review, then **Start pairing**. Only then perform the
   device's pairing gesture. Allow enough time to reach outdoor devices.
5. Follow HA's result, name the device and finish radio setup.

Agent: confirm a fresh sensor reading matches its display. Ask the user to try
a short valve run either disconnected from water or while visually checking
that it opens and closes. This is a recommended check, not a two-experiment
unlock requirement. Radio readiness and counter synchronization still apply.

Fresh single-zone pairing initializes the first command counter automatically;
the first normal watering response confirms it. Setup never waters automatically.
Check the roadmap for the tested release and remaining physical acceptance.

Finish with a summary of versions, nodes, paired devices and anything still
unverified. Dashboards and watering automations are a separate setup task.
Watering starts, stops and problems appear in HA's notification panel by default.
Mobile forwarding is optional; see [notifications](docs/ALPHA_NOTIFICATIONS.md).

## Limits and updates

HTV405 battery is not decoded and it has no water-volume capability. Alpha 1
firmware supports up to eight HTV145 associations per radio, sharing a custom
gateway identity. Older firmware retains its one-valve-per-radio limit.
Battery-change recovery and stock/local coexistence still need qualification.
Use a trusted LAN; see [security details](SECURITY.md) and the
[roadmap](PROJECT_ROADMAP.md) for full alpha limitations.
Operational connections now require matching TLS-capable gateway, integration
and firmware versions. Initial Wi-Fi/adoption setup still requires a trusted
network. Do not mix Alpha 1 with the earlier plaintext transport.

Updates are separate: app store for the gateway, HACS for the integration and
HA's radio Update entity once an agent/maintainer has staged a compatible
[publisher-signed firmware catalog](docs/ALPHA_BUNDLE.md#ota-for-an-already-adopted-node).
Unsigned build previews are not OTA releases. Fresh USB installs include the
public verification key; upgrading a pre-signing node needs the maintainer's
controlled bootstrap procedure first.

## Report issues

Use the [GitHub issue tracker](https://github.com/fholgado/rainpoint-local/issues).
Include device model, board/radio type, all three software versions, time and
timezone, what you tried, what happened, Wi-Fi RSSI and relevant diagnostics.
Mention whether the stock gateway was on and the valve connected to water.
Remove credentials and unrelated personal data from logs before sharing.
