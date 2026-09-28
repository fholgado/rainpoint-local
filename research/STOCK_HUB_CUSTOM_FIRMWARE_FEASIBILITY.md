# Stock RainPoint hub: custom-firmware feasibility

Offline assessment, 2026-09-27. No hardware access, flashing, security changes,
RF transmissions or runtime-code changes were performed. This is an engineering
assessment, not a second status checklist; priorities and completion belong in
[PROJECT_ROADMAP.md](../PROJECT_ROADMAP.md).

## Conclusion

**Using this hub as another RainPoint Local radio-node platform is plausible.**
The recommended eventual implementation is our own application using shared
protocol code and a new board/radio backend. It would replace the stock app,
not add a Home Assistant add-on inside it. The existing HA gateway/add-on would
remain the coordinator.

It is **not ready for a trial flash**. We have a readable, privately preserved
image and evidence of the ESP32-S3/CMT2300A platform, but not a verified board
pin map, complete active modem configuration, restoration trial, or compatible
build/release target. Keeping stock firmware intact for passive observation is
currently more valuable than replacing our reference implementation.

## What we actually know

| Evidence | Conclusion and boundary |
| --- | --- |
| PCB photos identify ESP32-S3-WROOM-1; both validated app descriptors identify ESP32-S3. | This is not the classic ESP32 target used by our nodes. Module suffix, memory mode and pin restrictions still need an explicit board inventory. |
| Two matching 8 MiB reads, validated application images, partition table at `0xA000`. | We have a strong backup baseline. Backup validation is not a demonstrated restore and is not a backup of silicon eFuses. |
| Saved backup manifest records `flash_encryption_enabled=false` and `secure_boot_enabled=false`. | The readout-time security snapshot supports a custom application trial in principle. Recheck before any write; this does not establish every download/anti-rollback setting or prove a restore. |
| Photo shows chip top marking `300A`; stock firmware contains CMT2300A RF identifiers. | The manufacturer identifies `300A` as CMT2300A (datasheet section 11). The radio backend differs from CC1101; recover the selected register writes and board wiring rather than copying a generic example. |
| Two 3 MiB OTA partitions, metadata selecting the newer image under standard IDF rules. | An inactive slot is a possible later trial location, not proof that arbitrary code can safely be installed or rolled back. |
| No original source, linker map, supported plugin interface or complete callable ABI recovered. | Adding a task to the proprietary app is not presently a source-level integration option. |

Local evidence: [validated inventory and analysis](STOCK_HUB_FIRMWARE_ANALYSIS_20260927.md),
[format/radio references](STOCK_HUB_FIRMWARE_REFERENCES.md), and
[implementation comparison](STOCK_HUB_IMPLEMENTATION_COMPARISON_20260927.md).

## Options compared

| Approach | What it enables | Assessment |
| --- | --- | --- |
| Passive UART/RF and radio-bus observation | Recover stock configuration, precise FIFO bytes, direction and timing while keeping stock behavior. | Best next research tool. A bus capture requires a verified pin map and a high-impedance, voltage-compatible analyzer; it must not drive a bus already owned by the ESP32. |
| Companion software through an existing stock interface | Potential local bridge while retaining stock pairing/control behavior. | No suitable local command API or UART command protocol has been established. The existing cloud integration remains cloud-dependent; it is not evidence of a local API. Investigate an interface before designing around it. |
| Full replacement application | Native RainPoint Local provisioning, ownership, protocol handling, OTA and HA integration on stock hardware. | Most maintainable product direction if hardware qualification succeeds. Requires a new radio backend and board target, but can reuse our verified protocol logic. Stock cloud operation would no longer run. |
| Binary patch/hook into stock application | Potentially export events or redirect a proven internal operation. | Technically conceivable, but currently the least maintainable option: version-specific addresses, unknown ABI/task ownership, image integrity, watchdogs and persistent-data layout. Prefer bounded research instrumentation only after a recovery plan, not a public product foundation. |
| Stock and custom applications in different OTA slots | Switch between reference and custom firmware across reboots. | They do not run simultaneously. Shared NVS/FAT/vendor storage can still be changed by either image. Separate slots alone do not isolate data or guarantee rollback. |

ESP-IDF OTA selects one application for boot, and rollback requires explicit
bootloader configuration/application validation; it is not implied by two
slots. [Espressif OTA documentation](https://docs.espressif.com/projects/esp-idf/en/v5.1.6/esp32s3/api-reference/system/ota.html).
Running our firmware on the second CPU core alongside an unmodified stock
image is likewise not a supported integration mechanism we have found; both
would need coordinated memory, scheduling, drivers and radio ownership.

## Actual porting work

Follow-up disassembly now identifies a six-bank configuration loader and a
tentative software-derived CSB/SDIO/SCLK/FCSB GPIO map. The
[instruction evidence](STOCK_HUB_FIRMWARE_ANALYSIS_20260927.md#radio-configuration-and-board-mapping-follow-up-evidence)
narrows the mapping work; it does not qualify physical wiring, active profiles
or interrupt pins. Do not use that candidate map as connection instructions.

The current build targets `esp32dev` in
`firmware/rainpoint_bridge/platformio.ini`. `src/main.cpp` constructs
`SPIClass(VSPI)` and a concrete `Cc1101`, with GPIOs 18/19/23/27/26/25.
Those values must not be applied to the S3 board. S3 has different available
GPIOs, flash/PSRAM reservations, strapping pins and USB assignments.
[Espressif S3 GPIO reference](https://docs.espressif.com/projects/esp-idf/en/v5.0/esp32s3/api-reference/peripherals/gpio.html).

Arduino supports S3 Wi-Fi, GPIO, UART and RMT, which makes reuse of our
transport and application logic plausible. It does not establish that our
currently pinned core, legacy `<driver/rmt.h>` usage or timing assumptions
compile and behave unchanged.
[Espressif Arduino feature matrix](https://docs.espressif.com/projects/arduino-esp32/en/latest/libraries.html).

| Layer | Reuse versus adaptation |
| --- | --- |
| Frame builders, validators and pairing state machines | Reuse hardware-independent `include/rainpoint_*` logic and native fixtures. Keep each known-working pairing prefix unchanged. |
| Radio operations | Introduce a small chip-independent interface for receive, tune, timed transmit, receive restoration and diagnostics. Keep the existing CC1101 implementation behavior unchanged. |
| Chip-specific parameters | Current transmit signatures expose CC1101 PA-table bytes and deviation-register values. Replace that boundary with physical intent/profile identifiers; CMT must independently map frequency, deviation, rate, power and tail behavior. Do not pretend matching register numbers are equivalent. |
| Timestamps and signal quality | Preserve receive-end timing semantics, not merely payload equality. CMT RSSI/status cannot be labeled CC1101 LQI or frequency-error measurements without an actual equivalent. |
| Board support | Map radio select/clock/data/interrupt pins, reset/power controls, button/LED polarity and any additional RF circuit. The other IC/antenna path in the photos is not identified well enough to assign a function. |
| Persistence and startup | Give custom configuration a deliberate layout. Do not initialize/erase vendor NVS simply because an example application does so. Boot with transmission disabled until ownership and configuration are valid. |
| Signed OTA and discovery | Existing `firmware_signature.h` validates `board=esp32dev` and `hardware_profile=esp32dev-cc1101-v1`; `wifi_transport.cpp` advertises that profile. Add an explicit S3/CMT target across manifests, discovery, signing and installation checks. Never relabel the old binary or relax cross-board checks. |

This is a hardware platform addition, not a return to retired sensor-only,
valve-only or bench production variants. Both platforms should share one
protocol implementation. Any additional build target needs an intentional
update to the current single-target contributor rule before implementation.

### CMT backend specifics

CMT2300A uses SCLK, bidirectional SDIO, register-select CSB and FIFO-select FCSB;
the manufacturer calls this a four-wire interface. Read-direction turnaround
and FIFO timing differ from register access. Its default separate 32-byte
RX/TX FIFOs can merge into a 64-byte buffer. This is not the CC1101
MOSI/MISO/CS transaction model.
[HOPERF datasheet, sections 5.1–5.2](https://www.hoperf.com/uploads/CMT2300A_Datasheet_EN_V1.8_202501029_1762138881.pdf).

Recover configuration writes at startup **and** mode/channel transitions.
Determine which preamble, sync, encoding and CRC bytes hardware adds/removes;
FIFO data alone is not necessarily the full over-air frame. In particular,
`AUTO_ACK_EN` does not autonomously acknowledge our sensors: it selects a
preamble-plus-sync packet format, and the MCU still initiates TX.
[HOPERF FIFO/packet guide, section 2.4](https://www.hoperf.com/uploads/AN143_CMT2300A_FIFO_and_Packet_Format_Usage_Guide_V1.1_202511_1764551828.pdf).

Manufacturer demo packages and RF configuration tools are indexed, but their
source compatibility and redistribution terms have not been reviewed. They
are possible references, not a chosen dependency.
[HOPERF CMT2300A resources](https://www.hoperf.com/ic/rf_transceiver/CMT2300A.html).

## Qualification sequence and decision evidence

This describes the proposed experiment, not authorization to flash or transmit.

| Stage | Evidence required to advance |
| --- | --- |
| Offline inventory | Verified boot/partition layout, current security-state record, recovered GPIO setup and RF initialization call paths; no assumptions from package pin labels alone. |
| Passive hardware mapping | Power-off continuity and passive logic capture confirm SCLK/SDIO/CSB/FCSB/interrupt wiring, active profile, FIFO framing and RX-to-TX timing. Correlate a known packet with SDR. |
| Build-only backend | S3 build passes, shared protocol tests remain unchanged/green, mocked register/FIFO tests check turnaround, limits and error recovery; signed manifests reject cross-board updates. |
| Receive-only trial on an explicitly approved spare/reference hub | Preserve stock data; validate UART recovery first, then bounded custom boot without RF TX. Compare received frames and timing to the stock capture. A RAM-only diagnostic may avoid app-flash changes if it fits, but still interrupts stock execution and requires approval. |
| Isolated transmit qualification | With explicit user approval and dry valves, compare complete waveform/timing and pass sensor ACK, both valve pair/control, restart and network-outage cases. Only then consider adoption as a production node. |

The MCU/build work appears bounded; unknown board wiring and CMT timing/profile
recovery dominate uncertainty. There is not enough evidence for a credible
calendar estimate yet. A working replacement will not itself explain the
remaining proprietary rejoin/counter behavior; protocol research remains useful.

## Preservation, security and publication boundaries

The private backup manifest separately records secure boot and flash encryption
disabled; this is stronger evidence than readable apps alone. It is still a
readout-time snapshot, not proof that an arbitrary replacement will boot.
Recheck the unit's read-only security summary before any write, including secure
boot, flash encryption, download restrictions and anti-rollback. Use recorded
status, not a guess from image hashes.
[Espressif eFuse summary](https://docs.espressif.com/projects/esptool/en/latest/esp32s3/espefuse/summary-cmd.html),
[secure boot](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/security/secure-boot-v2.html).

No eFuse burning, security enablement, key revocation or download-mode disabling
belongs in an exploratory port. Flash restoration cannot undo eFuses. A full
same-unit backup also contains private settings; preserve its exact layout and
do not clone it to another hub. Rewriting sectors or changing boot selection is
a distinct live operation, not part of this research.
[Espressif flashing behavior](https://docs.espressif.com/projects/esptool/en/latest/esp32s3/esptool/basic-commands.html),
[flash-encryption restrictions](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/security/flash-encryption.html).

For an open-source release, publish our source, independently expressed
protocol definitions and redacted tests—not the stock image, configuration,
credentials or proprietary code. Treat binary redistribution or patch bundles
as requiring a separate license/permission review; this is a project publication
boundary, not a legal conclusion. An available SDK or readable device backup
is not evidence of a license for the vendor application.
