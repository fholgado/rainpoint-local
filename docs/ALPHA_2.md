# Alpha 2

Alpha 2 is the current RainPoint Local prerelease for moisture sensors and
single-, two- and four-zone valves. Published October 5, 2026 (October 6 UTC),
it adds HTV213FRF two-zone support and removes dedicated-radio and manual-tuning
setup requirements. It supersedes the [Alpha 1 baseline](ALPHA_1.md) for new
installs and updates.

## Versions and downloads

| Component | Version | Installation |
|---|---|---|
| RainPoint Local Gateway | 0.39.19 | HA app/add-on repository; matched source archive below |
| RainPoint Local integration | 0.18.6 | [HACS release v0.18.6](https://github.com/fholgado/rainpoint-local/releases/tag/v0.18.6); enable prereleases |
| Unified ESP32/CC1101 radio | 0.21.0 | [Signed firmware release](https://github.com/fholgado/rainpoint-local/releases/tag/firmware-v0.21.0); USB for new boards, OTA for adopted radios |

Alpha 2 labels these already-published versions; it does not introduce another
tag, rebuild the firmware or change existing associations. Both release tags
point to `ff3ad1571c26278e1ce66a655cafcf5864a91a61`.

The firmware release includes `rainpoint-radio-0.21.0.zip` (signed USB/OTA
bundle), `rainpoint-source.tar.gz` (matched gateway and integration),
`compatibility.json`, `SHA256SUMS` and the agent testing guide. Verify checksums
before use. HACS installs only the integration, not the gateway or radio.

## What changed

- HTV213FRF native HA pairing, one device with two outlet controls, automatic
  and early stop, retained command phases, battery rejoin and restart recovery.
- Sensors and valves can share an updated radio, with up to eight independent
  HTV213 associations per radio. Existing associations and tuning overrides stay
  intact; manual tuning is optional.
- Valve naming preserves actual completion telemetry and its observation time.
- Response-window restoration, a rotating frequency cache and TCP backpressure
  improve handling of shared RF traffic and reconnect configuration bursts.

The existing sensor, HTV145FRF and HTV405FRF paths remain included. HA watering
start/stop/problem notifications are enabled by default; forwarding to a phone
is optional. No research switch, two-run unlock or 72-hour wait is required.

## Install or update

For a new installation, give an agent [Getting started](../GETTING_STARTED.md).
For an existing installation, use the [agent update and short testing guide](TWO_ZONE_ALPHA_TESTING.md).

Update and confirm **gateway 0.39.19 before any radio firmware update**. Gateway
0.39.18 can deliver 0.21.0 but rejects its new shared-radio capability on
reconnect. Update the integration separately, then stage the signed OTA catalog
and update one radio at a time. Confirm the new version, authenticated connection,
healthy boot and restored ownership; a completed download alone is not success.
Working devices do not need re-pairing just because software was updated.

Use the classic ESP32/CC1101 reference hardware and HA OS with Core 2026.7.0 or
newer. The [bundle guide](ALPHA_BUNDLE.md) covers pinned installs and recovery.
For first valve tests, either disconnect water or visually confirm that each
outlet opens and closes as expected.

## Validation and limitations

HTV213 enrollment/re-enrollment, both outlets, automatic/early stop, phase wrap,
battery rejoin and missing-response/restart recovery were qualified on the dry
test valve. Pairing and controls also worked with a same-batch spare radio.
Shared multi-device operation has source/replay coverage; physical mixed-device
feedback is still welcome. The full 1,077-test suite, production firmware build
and native protocol tests passed before publication.

- Other two-zone models are not qualified. HTV213 battery percentage and
  water-volume scaling remain unqualified.
- HTV405 battery status is not decoded and it has no water-volume capability.
- HTV145/HTV405 battery recovery and native phase allocation still need
  model-specific qualification; HTV213 results do not change their control paths.
- Independent fresh installs, multiple physical valves sharing a radio and
  stock/local coexistence remain tester work. Turn off the stock gateway for
  local pairing; automatic cloud migration is not implemented.

See [the roadmap](../PROJECT_ROADMAP.md) for current work and
[validation evidence](STOCK_INFORMED_VALIDATION.md) for detailed results.
Report successes and failures through [GitHub issues](https://github.com/fholgado/rainpoint-local/issues/new/choose),
including Alpha 2, all three versions, hardware/device models, timestamps,
actual opening/closing, HA states and relevant redacted diagnostics.
