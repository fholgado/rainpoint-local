# Stock hub Ghidra decompilation

2026-09-27; retained ESP32-S3 application **1.1.1040**. Offline only: no hub
connection, RF, upload of firmware, deployment or production-code changes.
Status belongs in [the roadmap](../PROJECT_ROADMAP.md).

## Result

**The technique works on this image.** Ghidra 12.1.4 imported all six application
segments and completed automatic analysis in 32 seconds, without reaching the
180-second limit. It identified 8,647 candidate functions; that is an analysis
count, not proof that every boundary or function is correct. Seven selected
functions exported C-like pseudocode without a function-level error:

| Entry | Selected role | Qualification |
| --- | --- | --- |
| `42037920` | Sequence generator | All 13 instructions checked against S3 objdump; exported C tested below. |
| `4203A344` | Master header builder | Pseudocode corroborates header `51`, command/length masks and six-bit sequence. |
| `4204A550` | Pending-reply matcher | Corroborates destination, sender, command and full-six-bit sequence predicates. |
| `4203FFE4` | Heartbeat defaults/override | Corroborates the previously checked `80`/`03` byte predicate. |
| `420403D4` | Channel allocator wrapper | Calls usage-count and selection helpers; wrapper alone does not explain allocation. |
| `4204A170` | Receive-header checks | Corroborates foreign-destination handling and record `+32` condition. |
| `4204ABA0` | Channel notification | Pseudocode exported; detailed semantics still rest on the earlier bounded assembly trace. |

An independent check re-read the original application's segment headers and
compared every segment's address, length and SHA-256 with bytes exported from
Ghidra's memory model: **all six matched**. The counter's exported C was compiled
in a host-only harness with one synthetic byte of state. It passed all 256
possible initial byte states and 256 consecutive masked output steps. This
qualifies that small function, not every inferred prototype or the whole image.

The generator increments a shared byte, replacing it with 1 when the *previous*
value exceeds 63. Its normal stored sequence is 1 through 64; the header builder
masks it to six bits, producing wire values 1 through 63, then 0. This agrees
with the [existing command-state analysis](STOCK_HUB_VALVE_STATE_TRACE.md).

A bounded cross-reference query found three references to the literal containing
the sequence byte's address, all inside the generator. This is **not proof that
there is no reset elsewhere**: indirect pointers, generic RAM initialization,
unrecognized code and persistence behavior are outside that query. The expanded
pass below subsequently found the bulk boot clear; an overnight-reset explanation
and valve-side acceptance rules remain unestablished.

## Expanded protocol pass

The follow-up exported **215 unique functions** across the initial selection,
protocol call chains, 185 direct configuration-access callers and boot/storage
helpers. All export-status records completed without errors or warnings. This
is successful pseudocode extraction, **not semantic qualification of 215
functions** or recovery of the original source.

Three findings now have concrete code paths:

- **Boot sequence initialization:** application entry `4037589C` calls ROM
  `memset` to clear `[3FCA42D0, 3FCACF20)`, which includes sequence byte
  `3FCA710F`. This proves zero at that startup stage. Later restoration or
  sequence consumption, historical overnight failures and valve acceptance
  remain separate questions. [Boot evidence](STOCK_HUB_BOOT_STATE_REFERENCE.md).
- **Retained reconnect condition:** an app gateway-identity change sets a
  migration flag; the device-list rebuild can then set record `+32`. The field
  lies within the 52-byte persisted prefix of a 184-byte runtime record, with
  a KV write/commit path. This explains a concrete trigger for the stock
  reconnect-result path, not a timeout or a way to wake silent sensors.
  [Recovery evidence](STOCK_HUB_SENSOR_RECOVERY_TRACE.md#gateway-identity-change-sets-and-persists-the-condition).
- **Terminal per-port data:** a fallback in parameter combiner `42025400`
  maps ID minus `32` to a port and returns its length-prefixed byte array.
  This fits the single-zone empty reply and four-zone 12-byte replies. Whether
  each captured model selects this fallback was initially unproven. The
  follow-up retained HTV145 descriptor qualifies it for fresh initialization
  with that table; HTV405 remains unresolved.
  [Descriptor evidence](STOCK_HUB_POSTBOOT_TRACE.md).

The additional [post-boot pass](STOCK_HUB_POSTBOOT_TRACE.md) exported 42 functions
(not claimed disjoint from the earlier 215), verified selected S3 instructions,
and CRC-checked the targeted generic HTV145 model descriptor. It also connects
cloud-gated startup notifications to sequence consumption before TX acceptance.
The [report-consumer trace](STOCK_HUB_REPORT_MODE_CONSUMERS.md) excludes captured
HCS026 from the class-0x50 mode-reply path. Neither establishes overnight-reset
causality or remote wake for silent soil sensors.

The retained-channel helper `42040410` also preserves a nonzero device-record
channel on its inspected mode-1 path, allocating only when it is zero. This
corroborates keeping a known association's channel during recovery; it does
not independently qualify a new over-the-air recovery exchange.

### Checks and reproducibility

Private `expanded-verification/manifest.json` records original-app hash, selected
literal assertions, export counts and bounded independent S3-objdump listings.
Boot clear bounds, ROM target, reconnect flag address and storage descriptor
length/type were re-read from the original app, not inferred solely from C.
The boot call, reconnect field store and parameter fallback branches were
cross-checked against assembly. Parameter branches were decoded at their actual
targets because linear decoding through padding gives misleading instructions.

Private exports are in `paths-1/`, `config-callers/`, `paths-2/` and `paths-3/`
beside the initial `qualified-exports/`. Retained helpers `ExportPaths.java`
and `verify_paths.py` reproduce extraction and the bounded checks. The stack-field
search helper is navigation only, not evidence of field semantics.

The 15 existing terminal-pairing, valve-frame, sensor-frame and compact-field
tests pass. They corroborate the captured wire interpretation; they do not
execute the vendor binary or prove device acceptance. No production code,
deployment, RF commands or live configuration changed in this pass.

## Adaptation of the proposed technique

The [supplied article](https://olof-astrand.medium.com/reverse-engineering-of-esp32-flash-dumps-with-ghidra-or-ida-pro-8c7c58871e68)
uses flash-to-ELF conversion followed by Ghidra/IDA analysis. We used that approach
but did not run the old converter unchanged. Tenable's
[image parser](https://github.com/tenable/esp32_image_parser/blob/master/esp32_image_parser.py)
hardcodes the original ESP32 loader, fixed segment-name assumptions and supplied
symbols; its [partition reader](https://github.com/tenable/esp32_image_parser/blob/master/esp32_firmware_reader.py)
assumes `8000`. Our table is at `A000`, and the target is S3. Injecting unrelated
ROM symbols would give misleading names, not recovered symbols.

A small private converter instead wraps the already-validated application in a
symbol-free ELF32/Xtensa container with six load segments and entry `4037589C`:

| Load address | Bytes | Analysis permission |
| --- | ---: | --- |
| `3C140020` | 268,028 | Read-only data |
| `3FC9EC00` | 22,224 | Read/write data |
| `40374000` | 37,404 | Executable |
| `42000020` | 1,266,920 | Executable |
| `4037D21C` | 71,912 | Executable |
| `600FE000` | 92 | RTC data; conservatively not marked executable |

These are image load addresses, not flash offsets. RTC memory can also host
code; the last row's conservative analysis permission is not a recovered linker
classification. No original section names, BSS bounds, debug symbols, ROM image
or source types were invented. See Espressif's
[S3 memory map](https://github.com/espressif/esptool/blob/master/esptool/targets/esp32s3.py)
and [image format](https://docs.espressif.com/projects/esptool/en/latest/esp32s3/advanced-topics/firmware-image-format.html).

## Reproduction and retained evidence

Tools were downloaded separately; production PlatformIO tools were not changed:

- [Ghidra 12.1.4](https://github.com/NationalSecurityAgency/ghidra/releases/tag/Ghidra_12.1.4_build),
  official archive SHA-256 `ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db`, verified.
- Temurin JDK 21.0.12.1+1, macOS ARM64; archive SHA-256
  `3623232f33a9c3baadf304480b2535f9a3cba8a58d42ecbb438ba267315d9998`,
  checked against [Adoptium's package metadata](https://api.adoptium.net/v3/assets/latest/21/hotspot?architecture=aarch64&image_type=jdk&os=mac&vendor=eclipse).
- Ghidra's supplied Gradle wrapper built the Mac-native decompiler successfully.
  [Release-specific setup](https://github.com/NationalSecurityAgency/ghidra/blob/Ghidra_12.1.4_build/GhidraDocs/GettingStarted.md).
- Bundled `Xtensa:LE:32:default`, compiler `default`; no legacy third-party
  processor plugin. [Language definition](https://github.com/NationalSecurityAgency/ghidra/blob/Ghidra_12.1.4_build/Ghidra/Processors/Xtensa/data/languages/xtensa.ldefs).

Private evidence directory, relative to this checkout:
`captures/stock-hub-firmware/2026-09-27-adzoj0e3/analysis/ghidra-20260927/`.
It contains the analysis ELF/manifest, persistent Ghidra project, selected C and
assembly exports, loaded-memory hashes, qualification results, scripts and logs.
It is Git-ignored with restricted permissions. Do not publish vendor C, firmware,
configuration or recovered identifiers. Tool installations currently live under
`/private/tmp/rainpoint-ghidra.r98i2D/`; reconstruct from pinned releases if removed.

After running the retained `reconstruct.py` against the validated app, the
headless command shape is:

```sh
analyzeHeadless ABSOLUTE_PRIVATE_PROJECT_DIR stock1040 \
  -import app-analysis.elf -processor Xtensa:LE:32:default -cspec default \
  -analysisTimeoutPerFile 180 -max-cpu 2 \
  -scriptPath PRIVATE_SCRIPT_DIR -postScript ExportSelected.java qualified-exports
```

Use JDK 21, a 2 GiB headless heap and restrictive permissions. A first attempt
using `.` as the project directory failed before import; the absolute path
succeeded. The follow-up uses `-process app-analysis.elf -noanalysis` against
the saved project, avoiding another import. The retained `check_mapping.py`
verifies segment hashes; `check_counter.c` includes only the reviewed small
counter export, not the vendor executable. This is not firmware emulation.

## How to use the output

Decompilation now makes call chains, field access and branches easier to inspect
for retained rejoin, terminal pairing and ACK state. It does **not** recover a
buildable original source tree. Inferred stack variables/prototypes remain noisy;
some apparent uninitialized values are fields populated through pointer arguments.
Resolve types and ABI before interpreting those as firmware bugs.

The bundled processor implements windowed calls, but S3-specific instructions
and hardware loops need separate qualification. An upstream
[Xtensa LOOP report](https://github.com/NationalSecurityAgency/ghidra/issues/9027)
documents a decompilation problem in 12.0.4; its existence is reason to check
affected constructs, not evidence that our seven exports are all wrong. Compare
meaningful branches with the [qualified S3 decoder](STOCK_HUB_DECODER_TOOLING.md)
and packet fixtures before using a new interpretation to change our protocol.
