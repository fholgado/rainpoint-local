# HACS distribution requirements and validation boundaries

Research date: 2026-09-10. Repository baseline inspected: `60985ab`.
This is a requirements/evidence note, not an acceptance record or another task
list. [PROJECT_ROADMAP.md](../PROJECT_ROADMAP.md) remains the sole live status
checklist. Fresh-install evidence belongs in
[ALPHA_INSTALL_VALIDATION.md](ALPHA_INSTALL_VALIDATION.md).

September 12 publication update: [Alpha 1](ALPHA_1.md), `v0.18.0-alpha.1`, is the
stack prerelease for HACS selection (integration 0.18.0). The separate
`firmware-v0.19.0` release distributes radio binaries; it is not the integration
install target. Use HACS's Download/Redownload version selector and opt into
prereleases as needed. The current repository remains in source-tree mode;
HACS does not consume the attached gateway source archive or radio ZIP.
[HACS version selection](https://www.hacs.xyz/docs/use/repositories/dashboard/#downloading-a-specific-version-of-a-repository).

## Distribution contract

HACS supports public GitHub repositories. Its publication requirements include
a repository description, topics, usage README and root `hacs.json`. The
`homeassistant` field declares a minimum HA version; `hacs` can likewise declare
a minimum HACS version. These declarations are compatibility constraints, not
proof that runtime behavior was tested.
[HACS general requirements](https://www.hacs.xyz/docs/publish/start/)

An integration repository should have one integration under
`custom_components/`, with its runtime files inside that integration directory.
HACS requires manifest identity, version, maintainer, documentation and issue
tracker metadata. RainPoint Local's inspected manifest provides those fields,
uses the distinct `rainpoint_local` domain and declares version `0.17.0`.
Its `hacs.json` uses the normal source-tree installation mode, not
`content_in_root` or `zip_release`.
[HACS integration requirements](https://www.hacs.xyz/docs/publish/integration/),
[repository manifest](../custom_components/rainpoint_local/manifest.json),
[repository HACS configuration](../hacs.json)

Users can add a custom repository through HACS's top-right menu, enter the
repository URL and choose the Integration type; default-store inclusion is a
separate distribution decision. Custom repositories still need a structure
HACS recognizes.
[HACS custom-repository instructions](https://www.hacs.xyz/docs/faq/custom_repositories/)

HACS installation here distributes the HA integration, not the separate gateway
app or firmware. Retain this boundary in installation instructions; a successful
HACS download cannot establish that the gateway is installed or a radio works.
[Project installation overview](../README.md),
[getting-started guide](../GETTING_STARTED.md)

## Gateway installation without copying files

HACS explicitly excludes Home Assistant OS apps (formerly add-ons); its
Integration type downloads into `custom_components/`. The gateway cannot be
installed by adding this repository to HACS, even though the same GitHub
repository contains both packages.
[HACS prerequisites](https://www.hacs.xyz/docs/use/download/prerequisites/),
[HACS integration installation](https://www.hacs.xyz/docs/use/repositories/type/integration/)

The simplest intended no-copy HA OS route uses two stores: add
`https://github.com/fholgado/rainpoint-local` under **Settings → Apps → Install
app → ⋮ → Repositories**, install **RainPoint Local Gateway**, configure and
start it; separately download the integration through HACS and restart HA.
The app repository already has the required root `repository.yaml` and an app
directory containing `config.yaml` and its Docker build sources. This is a
structurally supported distribution route, not evidence of a completed fresh
install or a guarantee that unpushed local changes are available there.
[HA third-party app repository instructions](https://www.home-assistant.io/common-tasks/os/#installing-a-third-party-app-repository),
[HA app repository requirements](https://developers.home-assistant.io/docs/apps/repository/),
[repository metadata](../repository.yaml),
[gateway app configuration](../rainpointd_addon/config.yaml),
[gateway Dockerfile](../rainpointd_addon/Dockerfile)

A documentation button can use this official redirect:
[Add RainPoint Local app repository](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Ffholgado%2Frainpoint-local).
It opens a repository-add dialog with the URL prefilled; it does not install or
start the gateway. The API identifier still uses `addon` despite the newer
user-facing “app” name.
[Official My Home Assistant redirect definitions](https://github.com/home-assistant/my.home-assistant.io/blob/main/redirect.json)

RainPoint Local currently accepts discovery from an already installed/running
gateway and asks the user to confirm integration setup. It does not add the
app repository, install the gateway, or start it from the integration flow.
[Existing Supervisor discovery flow](../custom_components/rainpoint_local/config_flow.py)

A more unified setup is technically possible as future integration work:
Home Assistant's `AddonManager` can install, configure and start a known app
through Supervisor, and the built-in Z-Wave JS flow demonstrates managed app
installation. This is an implementation precedent, not a HACS feature or a
currently implemented RainPoint capability. A RainPoint flow would additionally
need explicit user consent, third-party repository availability, correct app
identity, failure handling and separate non-Supervisor behavior, with fresh HA
OS validation. Keep any implementation decision in the canonical roadmap.
[HA app manager source](https://github.com/home-assistant/core/blob/dev/homeassistant/components/hassio/addon_manager.py),
[Z-Wave JS configuration flow](https://github.com/home-assistant/core/blob/dev/homeassistant/components/zwave_js/config_flow.py)

## Brand asset requirement

The current HACS integration documentation explicitly supports a local `brand/`
directory containing at least `icon.png`. For this repository the correct path
is `custom_components/rainpoint_local/brand/icon.png`, not a root-level
`brand/icon.png`. Older search-index copies of the HACS page still mention a
mandatory upstream brands submission; the directly fetched current page uses
the local asset requirement.
[HACS integration requirements](https://www.hacs.xyz/docs/publish/integration/)

The current HACS validator first checks that exact integration-local path in the
repository tree. Only when it is absent does it check whether the domain exists
in the legacy Home Assistant custom-brand registry. This check establishes file
presence, not PNG validity or correct frontend rendering. Do not suppress the
`brands` check to turn missing assets into a passing distribution claim.
[HACS brands validator source](https://github.com/hacs/integration/blob/main/custom_components/hacs/validate/brands.py)

Home Assistant supports integration-local brand images from version 2026.3.
Local assets take precedence over the remote brands repository. The existing
2026.7.0 minimum is therefore new enough for this mechanism; no upstream brands
PR is needed merely to serve the local icon. On an isolated HA instance, the
authenticated `/api/brands/integration/rainpoint_local/icon.png?placeholder=no`
endpoint distinguishes a real asset from a generic placeholder.
[Home Assistant brand images](https://developers.home-assistant.io/docs/core/integration/brand_images/)

Use a real 256-by-256 PNG icon; an optional 512-by-512 `icon@2x.png` supports
high-density displays. These dimensions follow the official brands image
specification, although the HACS presence check does not enforce them. Prefer
lossless compression and transparency where appropriate. Avoid Home Assistant
branded imagery that would imply the custom integration is official. A
project-owned asset with documented provenance avoids introducing uncertain
third-party artwork into the package.
[Home Assistant brands specification](https://github.com/home-assistant/brands#image-specification)

## Official validation

The inspected CI runs project Python tests, source-package smoke/determinism
checks, native firmware tests, firmware builds and an amd64 gateway-container
check. It does not run HACS validation or hassfest. Existing distribution tests
check selected local metadata; they are explicitly not HACS/HA OS acceptance.
[Current CI](../.github/workflows/ci.yml),
[distribution tests](../tests/test_distribution_metadata.py)

Add independent Ubuntu CI jobs using `hacs/action@main` with
`category: integration`, and `home-assistant/actions/hassfest@master` after
`actions/checkout@v6`. HACS documents push and pull-request validation against
the event branch; release/default-branch validation can target different content.
Record the event, source SHA and validator version/image alongside each result.
Keep mandatory checks enabled. A scheduled run can detect changing upstream
rules, and manual dispatch permits explicit revalidation.
[HACS validation action](https://www.hacs.xyz/docs/publish/action/),
[official hassfest setup](https://developers.home-assistant.io/blog/2020/04/16/hassfest/)

The HACS action accepts `comment: "false"`; use it to avoid unsolicited PR
comments while retaining validation output. Its implementation runs a container
from `ghcr.io/hacs/action:main` and uses the GitHub token by default. A successful
local metadata test is not equivalent to running that remote-repository-aware
validator. Do not claim an exact HACS release was tested merely because the
action uses `main`.
[HACS action definition](https://github.com/hacs/action/blob/main/action.yml)

For a local official hassfest run on a Docker-capable development host, the
current action implementation mounts the workspace into the official image.
The corresponding command from the repository root is:

```bash
docker run --rm -v "$PWD:/github/workspace" ghcr.io/home-assistant/hassfest
```

This is a proposed command, not evidence that it ran here. The action currently
uses the unqualified image name, so capture its resolved digest for a repeatable
record. Hassfest validates integration data; its success does not exercise the
full config flow or prove runtime compatibility.
[Current hassfest action implementation](https://github.com/home-assistant/actions/blob/master/hassfest/action.yml),
[hassfest purpose](https://developers.home-assistant.io/blog/2020/04/16/hassfest/)

## Update channels and compatibility evidence

Without published releases, HACS downloads the default branch. Published GitHub
releases offer release selection as well as the default branch. A Git tag alone
is not enough to establish release-based updates. `hide_default_branch` can
remove that development choice once an intentional release channel exists.
`zip_release` requires a named ZIP asset; it is not necessary for this existing
source-tree integration, and the project's gateway/firmware alpha bundle should
not be presented as an integration-only HACS ZIP.
[HACS integration releases](https://www.hacs.xyz/docs/publish/integration/),
[HACS version and archive settings](https://www.hacs.xyz/docs/publish/start/)

For an eventual alpha, select a release version and GitHub prerelease policy
explicitly. HACS provides a per-repository switch controlling whether update
checks consider prereleases; the switch entities are disabled by default and
must first be enabled. Instructions should name the selected version and explain
the opt-in, rather than promising that every user automatically receives alphas.
Publishing or changing releases remains a separate authorized operation.
[HACS prerelease switches](https://www.hacs.xyz/docs/use/entities/switch/)

The HA manifest version is required for custom integrations and must be
recognized by AwesomeVersion. Keep release identity and manifest identity
consistent, including asset-only integration updates, so installed evidence can
identify the exact source. The domain must match its directory and must remain
stable. This note does not propose a domain or branding rename.
[Home Assistant integration manifest](https://developers.home-assistant.io/docs/creating_integration_manifest/)

The repository declares HA 2026.7.0 consistently in HACS and the app manifest,
but the inspected Python CI uses Python 3.12 and installs only PyYAML and Jinja2;
it does not install and run actual Home Assistant. Recommend a separate runtime
test matrix at the declared minimum and a current supported HA release, using
the Python runtime required by each HA version. Treat forthcoming-version
hassfest results as early compatibility signals, not runtime guarantees.
[CI](../.github/workflows/ci.yml),
[test requirements](../tests/requirements.txt),
[app manifest](../rainpointd_addon/config.yaml)

## What requires a fresh instance

Local tests and official validators can establish packaging structure, asset
validity, manifest consistency and integration-data conformance. CI with real
HA can additionally exercise config-entry setup/unload, discovery and entity
behavior against an empty mocked gateway. Neither category proves that a new
user can install the complete system independently.

Acceptance still requires an isolated fresh HA OS instance: actual HACS custom
repository addition and selected-channel download, restart, visible local
branding, gateway app discovery/startup, config flow, update/restart behavior
and clean removal/reinstallation without copied household state. Record the HA,
HACS, integration, gateway and firmware versions, source SHA and actual UI
outcomes. Physical provisioning, sensor ownership, dry valve association and
duration-bounded open/stop tests require the separately controlled hardware
procedure. This separation follows the project's existing evidence policy;
an already configured household is not a fresh-install substitute.
[Independent installation evidence policy](ALPHA_INSTALL_VALIDATION.md)

No official validation, release publication, artifact upload or live Home
Assistant change was performed as part of this research note.
