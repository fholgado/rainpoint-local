# Captured replay example

These original installation labels identify historical cloud payload captures.
They are example inputs, not a default device catalog. Replay is observation-only
and requires an explicit fixture file when launching the gateway.

```sh
PYTHONPATH=rainpointd_addon python3 -m rainpointd --transport replay --replay-fixtures examples/captured-replay/fixtures.json
```
