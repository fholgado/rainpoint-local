# Alpha 1

Released September 12, 2026 as
[`v0.18.0-alpha.1`](https://github.com/fholgado/rainpoint-local/releases/tag/v0.18.0-alpha.1).
This is the first public alpha of the complete RainPoint Local stack, separate
from the existing cloud integration. Builders with supported sensors and either
valve family are welcome to help test it.

## Version combination

| Component | Version | Installation |
|---|---|---|
| RainPoint Local Gateway | 0.39.0 | HA app/add-on repository |
| RainPoint Local integration | 0.18.0 | HACS; select `v0.18.0-alpha.1` |
| Unified ESP32/CC1101 radio | 0.19.0 | Bundled USB images; signed OTA for existing compatible nodes |

Alpha 1 is a release label for these existing versions, not a new firmware build
or a stable-release claim. The firmware is byte-identical to the separately
published [`firmware-v0.19.0`](https://github.com/fholgado/rainpoint-local/releases/tag/firmware-v0.19.0)
release, built from `5dc0c5fc8886ffa49c7cccccd3c50beb93dd46d6`. The stack tag
contains newer documentation; `compatibility.json` records the separate source
and signed-firmware revisions. Existing installations on this combination do
not need a reflash, re-pair or database reset merely to adopt the alpha label.

## Get started

Follow [Getting started](../GETTING_STARTED.md) with an agent: install the gateway
and integration, wire/flash the radio, configure Wi-Fi and adopt it in HA. Then
pair sensors or valves in HA. Use HA OS with Core 2026.7.0 or newer and the classic 4 MB
ESP32 reference hardware. Both aarch64 and amd64 gateway builds are declared;
independent install reports on each are welcome.

Release downloads include `rainpoint-source.tar.gz` (gateway and integration),
`rainpoint-radio-0.19.0.zip` (USB parts, signed OTA catalog and instructions),
`compatibility.json` and `SHA256SUMS`. The source archive is not an HA backup.
The [bundle guide](ALPHA_BUNDLE.md) covers pinned source installation and updates.
The app store follows the repository's default branch; verify gateway 0.39.0
before installing or use the pinned source archive. HACS installs only the
integration, not the gateway or firmware.

## What is included

- Local pairing and moisture reports for HCS02x/HCS026FRF sensors.
- HTV145FRF single-zone and HTV405FRF four-zone pairing and bounded controls,
  device-reported state, ACK handling and counter synchronization.
- Wi-Fi radio discovery/adoption, diagnostics and publisher-signed OTA support.
- HA watering start/stop/problem notifications by default; optional mobile
  forwarding. Household dashboards and watering automations are not installed.
- Independent custom gateway identities and persistent device/ACK ownership.

## Known limitations and tester focus

The reference installation has exercised both valve families and sensors, TLS,
signed OTA and network-outage recovery. Automated tests cover fresh gateway
storage and real HA Core flows. These do not replace independent physical setup.
The remaining [roadmap acceptance work](../PROJECT_ROADMAP.md#alpha-cohort-preparation)
is now alpha-cohort work, not a reason to withhold this prerelease:

- Fresh HA OS app/HACS installation, Wi-Fi adoption and the complete pairing,
  cancellation, deletion and re-enrollment UI on new users' hardware.
- Longer-term reporting/control reliability, battery-change recovery and
  coexistence with the stock RainPoint gateway. Turn the stock gateway off
  while pairing; automatic cloud migration is not implemented.
- Multiple single-zone valves owned by one radio: eight slots are implemented,
  but physical multi-valve isolation still needs qualification.
- HTV405 battery status is not decoded; this model has no water-volume
  capability. HTV145 exposes categorical battery and reported water usage;
  further comparisons against real watering are welcome.
- HA Container standalone manual TLS setup is not yet a supported onboarding
  path; use HA OS and gateway discovery for this alpha.

For first valve tests, either disconnect water or visually confirm opening and
closing. A successful pairing indication alone does not prove working controls.
Keep another way to water while evaluating reliability. Initial setup requires
a trusted LAN; operational connections use TLS. See [security](../SECURITY.md)
and [notification behavior](ALPHA_NOTIFICATIONS.md).

Report results through [GitHub issues](https://github.com/fholgado/rainpoint-local/issues/new/choose),
including the Alpha 1 label, all three component versions, hardware/device
models, timezone/timestamps, steps and observed results. Note stock-gateway
power state and whether the valve was dry. Redact credentials and personal data.
Both successes and reproducible failures help complete the roadmap.
