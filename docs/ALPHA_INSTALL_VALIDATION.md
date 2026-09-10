# Independent installation validation evidence

The single live checklist remains [PROJECT_ROADMAP.md](../PROJECT_ROADMAP.md).
This document separates reproducible package checks from an actual new-user
installation. It does not mark HACS, HA OS or radio adoption accepted.

## Automated evidence

- CI and `tools/package_release.py --smoke-test` extract only tracked runtime
  files into a temporary installation, start an empty gateway twice using its
  own SQLite store, check an empty device/registry response and reject an absent
  mutation credential. No household catalog, database or radio is contacted.
- `tools/package_alpha.py` consumes PlatformIO's real build receipt and validates
  firmware version, source commit, clean source, image digests, the four USB
  parts/offsets, both OTA slot capacities and production command boundaries.
  The committed-source 0.17.0 build produced the same application digest as the
  installed image; only packaging/build metadata changed, not RF logic.
- Local clean-source candidate bundles from commit `7062ad8` matched byte for
  byte across two runs. CI for that commit passed Python, firmware/package and
  container jobs. This proves package determinism for fixed inputs, not physical
  first-flash success or reproducibility of all compiler/toolchain versions.
- Distribution tests enforce a single `rainpoint_local` integration directory,
  required metadata, a nonempty maintainer, a separate cloud-independent domain,
  consistent HA version declarations and the alpha report template.
- Official HACS and hassfest checks passed on `6541df2` in
  [CI run 34467939697](https://github.com/fholgado/rainpoint-local/actions/runs/34467939697).
  Hassfest exposed an existing missing `network` dependency used by adoption,
  then incorrect manifest key ordering; both now have source/metadata regressions.
  This is integration-data validation, not a real HA setup/commissioning test.

## What these checks do not cover

No isolated HA OS machine or browser-control tool was available for this pass.
The developer computer has no configured Docker executable. The extracted
gateway smoke test does not exercise Supervisor discovery, HACS installation,
frontend selectors, physical BOOT adoption, Wi-Fi commissioning or actual valve
pairing. The container CI currently exercises amd64, not a complete aarch64
fresh-install test. Do not use the existing configured house as proof of a
household-independent installation.

The integration now includes original local `brand/icon.png` and `icon@2x.png`
assets with editable source and PNG structure/dimension regressions. Current
[HACS integration requirements](https://www.hacs.xyz/docs/publish/integration/)
include brand assets. Official HACS and hassfest jobs are now configured in CI;
their results must be checked per revision. Metadata unit tests are not a
substitute for those validators or a real HACS install. Without a published release, HACS follows the
default branch; an alpha needs an intentionally selected update channel.

On a new HA OS test instance, follow the getting-started guide with an empty
gateway, no copied credentials/IDs, a self-built node and each supported device
family. Capture versions, UI results, association ownership and physical outcomes
using the alpha issue form. Keep the tests dry until open and both stop modes
are independently observed. Record results in the roadmap rather than creating
another status list here.
