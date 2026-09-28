# Stock receive-channel change and startup notification

Offline instruction trace, 2026-09-27. Source: retained HWG023WBRF-V2
ESP32-S3 firmware **1.1.1040**; addresses below refer only to that image.
No channel, pairing, firmware or live device state was changed. Status belongs
in [the roadmap](../PROJECT_ROADMAP.md).

## Result

**Correction, Sep 28:** slot 3 is the `subdev_ver` table. The notifier's first
data byte was previously mislabeled a per-device channel; it is a configuration
update version. Setter and serializer evidence is in the
[pairing configuration trace](STOCK_HUB_PAIRING_CONFIGURATION_TRACE.md).

**Static evidence:** the app's `ReciCH` property is not merely a display label.
A changed numeric value reaches a subdevice parameter-update builder. It
constructs native command **`0x20`**, with body:

```text
[per-device configuration version][update kind 4][new gateway receive selector]
```

Separately, `app_main` invokes the same notification family during startup,
using kind **1**, without the third body byte. Both paths use the ordinary
master-header sequence generator. This provides a concrete source of
non-watering sequence advancement before the first valve command; it does
not prove when a valve resets or accepts a sequence.

No retained experiment has yet established successful device retuning in
response to this channel-change message. Do not turn this trace into a live
channel migration or sleeping-device recovery command without that evidence.

## App property to persisted configuration

The diagnostic name `_bd_app_parse_property` is referenced through literal
`0x42000F18`; its function begins at `0x4200EC64`.

| Instructions | Observed operation |
| --- | --- |
| `0x4200ED6D..82` | Allocate/clear a 224-byte gateway configuration at stack +24; read configuration slot 1 through `0x4201DF80(2, 1, pointer)`. |
| `0x4200F3F1..FD` | Parse numeric `ReciCH`, string at `0x3C1476B0`, using `0x4200E7EC`. |
| `0x4200F406..410` | Compare the existing byte at stack +188 with the parsed integer; write the changed value back as one byte. This is configuration offset **164**. |
| `0x4200F425`, `0x4200F42A`, `0x4200F44A` | Set the change flag to 1 for a changed value, or 0 for unchanged/absent. |
| `0x4200F661..678` | Pass configuration at stack +24 to `_bd_app_update_gw_app_info` (`0x4200D6A0`); a nonzero result bypasses subsequent notification. |
| `0x4200F6B4..BB` | If the change flag is set, call `0x4204BBC0(1)`. |

`_bd_app_update_gw_app_info` is named by literal `0x42000C90`. On its normal
update branch, `0x4200D724..72D` calls configuration dispatcher
`0x4201DF80(1, 1, configuration)`. This establishes the setter invocation before
the notification reads slot 1 again; it does not independently prove a
flash-write completion boundary or behavior during power loss.

Another property path calls `0x4204BBC0(1)` at `0x420104CA`, guarded by a flag
at stack +`0x2F8`. The fully traced simple-property path above is sufficient
to establish causality; the nested-property parser is not assumed identical
in validation or persistence behavior.

## Notification selection and recipients

`0x4204BBC0` is identified by its own diagnostic literal as
`bd_sdev_comm_inform_change_main_recv_channel`. Its argument **1 is a reason/
kind selector, not RF channel 1**.

- `0x4204BBDE..BC18`: return early for an exclusion helper, lack of
  bidirectional RF support (explicit `GW not support bid rf` diagnostic), or
  argument zero.
- `0x4204BC63..BCC5`: iterate candidate address slots from an initial-index
  helper through index 39; read each device's 184-byte configuration from
  slot 4 and apply several eligibility predicates. This is not an unconditional
  broadcast to every paired device.
- `0x4204BCCA..BCDF`: if the resulting list is empty, insert address 1 as a
  fallback. The wire semantics of this fallback are not established here.
- `0x4204BCE1..BCEF`: argument 1 maps to update kind **4**; argument 2 maps to
  kind **1**.
- `0x4204BCF1..BD25`: reload gateway configuration slot 1, take byte +164,
  and call `0x4204ABA0(recipient_list, count, kind, &configuration[164])`.

The filters involve `0x4201EDDC`, `0x4212AFE4`, `0x4212B7CC` and
`0x42037968`. Their precise product eligibility and offline-device treatment
are not sufficiently traced to promise that sensors and both valves all
receive the notification.

## Native message construction

`0x4204ABA0` is named `bd_sdev_comm_inform_sdev_param_update` by literal
`0x420412AC`. The following offsets refer to the **native payload**, not the
one-bit-shifted normalized capture representation described in
[the radio frame trace](STOCK_HUB_RADIO_PATH_TRACE.md).

| Native field | Instruction evidence |
| --- | --- |
| Byte 12: per-device configuration version | `0x4204ABF0..BF7` reads slot 3 (`subdev_ver`) into a 40-byte table. `0x4204AC10..28` selects `table[address - 1]` and writes stack +78. |
| Byte 13: update kind | `0x4204AC2B..2E` writes kind to stack +79. |
| Byte 14: new value, conditional | `0x4204AC31..45` appends the pointed-to byte only for kind 3 or 4 with non-null value pointer. |
| Header command `0x20`, body length 2 or 3 | `0x4204ACD0..ACE6` calls master-header builder `0x4203A344` with command 32, destination address, body length and header pointer stack +66. |
| Queue/transaction handoff | `0x4204AD01` packs the internal wrapper with `0x42037ECC`; `0x4204AD21` calls `0x4204A8E0` with command 32 and returned header metadata. |

This proves construction and handoff, not receipt, ACK, retry completion or
durable retuning by a device. The first body byte is the per-device update
version, not an RF selector; it must not be replaced with the new receive selector.

## Startup traffic and the global sequence

`app_main` at `0x42013564` is identified by its diagnostic literal
`0x4200137C -> 0x3C14808C`. Its initialization sequence directly calls
`0x4204BBC0(2)` at `0x42013597..99`. After the guards/recipient filtering above,
this produces command `0x20`, body length 2:

```text
[per-device configuration version][update kind 1]
```

The notification builder calls the same master-header builder as valve
controls. That builder calls global sequence generator `0x42037920` at
`0x4203A435` and masks its result to six bits at `0x4203A438` before placing it
in native header byte 9. The generator increments byte `0x3FCA710F`; old values
above 63 wrap to 1, while stored value 64 encodes as sequence 0.

Therefore startup parameter messages can consume sequence values before any
watering command, one header per selected recipient. This is an explanation
candidate for a stock hub's first observed valve-control sequence not being 1.
It does **not** show a valve's expected sequence, a reset instruction, a wake
signal, or that restarting our node should send this packet.

## Capture corroboration and remaining uncertainty

An offline scan of the redacted public JSON fixtures found nine unique native
command-`0x20` frames: five length-2 bodies `02 00` and four length-1 bodies `00`.
They occur in existing valve enrollment/configuration captures and local
candidate/calibration fixtures, not a labelled app-channel-change experiment.
None corroborates the newly traced kind-4 or startup kind-1 body. Their shared
command number supports a parameter/configuration family, not interchangeability
with enrollment or a successful migration claim.

The [radio trace](STOCK_HUB_RADIO_PATH_TRACE.md) separately establishes the
low-level selector transform: subtract one, swap indices 1 and 14, add 66 in
one mode, then program CMT register `0x63`. This note has not closed the full
gateway-configuration +164 → radio-context receive selector chain, nor proven
the app's visible labels/range or the resulting absolute frequencies. The
notified new selector, configuration version, per-device RF channel and physical
register index remain distinct; controlled before/after RF evidence is still
needed for channel-change acceptance.

## Reproducibility and privacy

Primary source is the private retained `app-ota_1.bin`, IROM loaded at
`0x42000020`, analyzed with the ESP32-S3-aware objdump and bounded disassembly
at the listed entry/branch addresses. Restart disassembly at branch targets
when padding confuses linear decoding. Existing private firmware/disassembly
remain under the Git-ignored capture directory; no binary, configuration,
credential or installation identifier is included here.

No channel-reference test was added: a test that merely restated this static
interpretation without an independently captured accepted transaction would
not establish behavioral correctness. Existing public frame-boundary tests
remain the independent representation check.
