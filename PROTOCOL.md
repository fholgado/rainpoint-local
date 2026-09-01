# RainPoint RF protocol

The current protocol definition is organized by device under
[`protocol_documentation/`](protocol_documentation/):

- [Shared RF, framing, integrity, and state rules](protocol_documentation/common.md)
- [Stock RainPoint gateway behavior (`HWG023WBRF-V2`)](protocol_documentation/hwg023wbrf-v2.md)
- [Soil-moisture sensors (`HCS02x` / `HCS026FRF`)](protocol_documentation/hcs026frf.md)
- [Single-zone valve (`HTV145FRF`)](protocol_documentation/htv145frf.md)
- [Four-zone valve (`HTV405FRF`)](protocol_documentation/htv405frf.md)

Start with the [protocol documentation index](protocol_documentation/README.md)
for support status and interpretation rules.

This file remains as a stable entry point for existing links. It intentionally
contains no experiment journal or project checklist. Dated findings and capture
procedures are retained in
[`research/RF_CAPTURE_NOTES.md`](research/RF_CAPTURE_NOTES.md), exact wire
evidence is under [`research/fixtures/`](research/fixtures/), and active work is
tracked only in [`PROJECT_ROADMAP.md`](PROJECT_ROADMAP.md).
