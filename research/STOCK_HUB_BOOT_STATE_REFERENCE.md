# Stock hub boot state: shared sequence byte

Research date: 2026-09-27. Scope: retained stock ESP32-S3 application analysis
and Espressif ESP-IDF **v5.1.6** primary sources. No device/cloud queries,
deployment, runtime changes, or reset experiment were performed. Upstream
startup behavior is a reference, not proof that every stock startup instruction
or linker choice matches unmodified IDF.

## Finding

**The recovered stock application entry contains a bulk zero-fill covering the
shared sequence byte.** The ROM target is independently identified below;
the stock decompilation was cross-checked against ESP32-S3 objdump. This proves
zero at that startup stage, not the first transmitted sequence, absence of
later restoration, an overnight reset, or a valve-side acceptance rule.

The qualified generator at `0x42037920` updates byte `0x3FCA710F`; callers use
six bits. The retained application DRAM load segment covers
`[0x3FC9EC00, 0x3FCA42D0)`, length `0x56D0` (22,224 bytes), so it contains no
initialized image byte for this address. Qualified direct-literal references
found only the generator. Original ELF symbols and all pointer aliases remain
unavailable. Absence of a direct reference does not exclude a bulk clear,
structure copy, computed pointer, or restore operation. These are static
findings and limitations from the
[sequence trace](STOCK_HUB_VALVE_STATE_TRACE.md#persistence-and-reset-limits).

### Recovered stock entry zero-fill

The current stock entry decompilation at `0x4037589C` calls through literal
`0x403744B4`, whose value is `0x400011E8`, with arguments:

```text
destination = *(uint32_t *)0x40374460 = 0x3FCA42D0
fill        = 0
length      = *(uint32_t *)0x4037445C - destination
            = 0x3FCACF20 - 0x3FCA42D0 = 0x8C50
```

Espressif's pinned S3 ROM linker map defines `memset = 0x400011e8`, so the
resolved operation is `memset(0x3FCA42D0, 0, 0x8C50)`.
[ESP-IDF v5.1.6 S3 ROM newlib symbols, line 17](https://github.com/espressif/esp-idf/blob/v5.1.6/components/esp_rom/esp32s3/ld/esp32s3.rom.newlib.ld#L17).

The call is at `0x403758C9`; the branch around the separate RTC clear follows
at `0x403758CC`. Independent ESP32-S3 objdump confirms argument loads into
`a10`/`a12`, subtraction for length, zero in `a11`, and `callx8` through the
resolved ROM function pointer. Retained private evidence is
`analysis/ghidra-20260927/paths-2/4037589c.c` and `.asm` under the stock firmware
capture bundle; this note records only code addresses and non-private bounds.

The byte `0x3FCA710F` is inside `[0x3FCA42D0, 0x3FCACF20)`. Unlike inference
from missing load-segment coverage, this directly identifies a bulk operation
which clears the byte whenever execution reaches this unconditional call.
The distinct conditional RTC clear has equal bounds `0x50000000`, so it does
not describe or exempt this DRAM byte. These stock arguments are recovered
and assembly-cross-checked evidence, not values inferred from the generic IDF
linker template.

## What upstream startup actually establishes

| Stage or section | ESP-IDF v5.1.6 behavior | Consequence for this byte |
| --- | --- | --- |
| `call_start_cpu0` | Unconditionally clears the linker range `[_bss_start, _bss_end)` before higher-level initialization. Separately clears RTC BSS unless reset reason is `RESET_REASON_CORE_DEEP_SLEEP`. | The recovered stock bulk-clear range contains the byte and matches this startup pattern; the stock numeric arguments establish coverage without original ELF symbols. |
| S3 linker layout | Declares `.dram0.data`, then distinct `.noinit (NOLOAD)` and `.dram0.bss (NOLOAD)` sections. Only the latter is bounded by the ordinary BSS symbols. | Outside the initialized segment alone could not distinguish these sections. The newly recovered actual zero-fill resolves whether this entry clears the byte, independently of its original section name. |
| `start_cpu0_default` | Calls `do_core_init`, `do_global_ctors`, `do_secondary_init`, then `esp_startup_start_app`. `do_secondary_init` dispatches registered component initialization. | Startup includes opportunities to modify or restore state after the early clear. |
| FreeRTOS application start | `esp_startup_start_app` creates `main_task`; that task later calls `app_main`. Returning from `app_main` deletes the main task. | Calling or returning from application code is not itself a repeat of the early BSS-clear path. |

Primary sources: [CPU startup](https://github.com/espressif/esp-idf/blob/v5.1.6/components/esp_system/port/cpu_start.c),
[ESP32-S3 section layout](https://github.com/espressif/esp-idf/blob/v5.1.6/components/esp_system/ld/esp32s3/sections.ld.in),
[system startup](https://github.com/espressif/esp-idf/blob/v5.1.6/components/esp_system/startup.c),
[FreeRTOS application startup](https://github.com/espressif/esp-idf/blob/v5.1.6/components/freertos/app_startup.c).

The early clear is software behavior, not a claim that a CPU reset electrically
erases all SRAM. The S3 `esp_restart_noos` implementation resets CPUs after
shutdown preparation; `call_start_cpu1` is a separate secondary-core startup
path and does not perform the ordinary shared BSS clear. Consequently, reset
scope and the path actually executed matter; restarting a task or protocol
subsystem cannot be equated with running `call_start_cpu0`.
[S3 reset implementation](https://github.com/espressif/esp-idf/blob/v5.1.6/components/esp_system/port/soc/esp32s3/system_internal.c),
[CPU startup](https://github.com/espressif/esp-idf/blob/v5.1.6/components/esp_system/port/cpu_start.c).

## Persistence distinctions

- **Ordinary DRAM/BSS:** a proven BSS clear establishes a value at one startup
  stage, not the eventual first transmitted sequence. The stock `app_main`
  notification path already consumes the shared sequence through its header
  builder; it can advance the value before a user valve command.
  [Stock channel-change/startup trace](STOCK_HUB_CHANNEL_CHANGE_TRACE.md).
- **DRAM `.noinit`:** IDF explicitly documents that this section is not
  initialized at startup and should retain values across a software restart.
  This is not a guarantee of retention across power loss. The recovered stock
  clear covers this byte, so `.noinit` cannot justify retaining its prior value
  through that operation; any later restore is a separate question.
  [IDF memory types](https://github.com/espressif/esp-idf/blob/v5.1.6/docs/en/api-guides/memory-types.rst).
- **RTC memory:** S3 RTC FAST/SLOW regions are separate from this DRAM address;
  upstream places them at `0x600FE000` and `0x50000000` respectively, with
  configuration-dependent reserved portions. Their deep-sleep handling does
  not make a DRAM global retained. An application could copy between storage
  classes, but no such copy for this byte is demonstrated.
  [S3 memory regions](https://github.com/espressif/esp-idf/blob/v5.1.6/components/esp_system/ld/esp32s3/memory.ld.in),
  [CPU startup](https://github.com/espressif/esp-idf/blob/v5.1.6/components/esp_system/port/cpu_start.c).
- **NVS:** IDF NVS stores keyed values in flash through explicit read/write
  APIs. A RAM global can therefore be a working copy of persistent state;
  merely finding a RAM address or NVS partition establishes neither saving
  nor restoration of that particular byte. The qualified stock trace has no
  demonstrated sequence save/restore path.
  [IDF NVS](https://github.com/espressif/esp-idf/blob/v5.1.6/docs/en/api-reference/storage/nvs_flash.rst),
  [stock persistence limits](STOCK_HUB_VALVE_STATE_TRACE.md#persistence-and-reset-limits).

## Named stock reset leads are not counter-reset evidence

The existing reference identifies `bd_sdev_comm_process_mcu_abnormal_restart`
at `0x42051FD0`, with product-dependent branches and an MCU-restart diagnostic,
and `bd_sdev_comm_inform_dev_ser` at `0x42052280`, which can call parameter-update
helper `0x4204B874`. Neither is a demonstrated setter for `0x3FCA710F`, valve
battery-rejoin rule, or command-counter reset. The name `ser` must not be
expanded into sequence-counter semantics.
[Stock reference](STOCK_HUB_FIRMWARE_REFERENCE.md#5-acks-recovery-and-report-health),
[original bounded analysis](STOCK_HUB_FIRMWARE_ANALYSIS_20260927.md#acks-counters-and-restart-leads-with-important-boundaries).

A defensible first-transmission conclusion requires following subsequent
writes/restoration and sequence consumption after the recovered clear. Even
that would describe hub startup behavior only: proving that an observed
overnight change was caused by reboot requires independent reset/event
evidence, and valve acceptance remains a separate question.
