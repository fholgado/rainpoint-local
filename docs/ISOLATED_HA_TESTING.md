# Isolated Home Assistant installation testing

Research checked 2026-09-11. This is a test-environment procedure, not acceptance
evidence or another checklist. Track results in
[PROJECT_ROADMAP.md](../PROJECT_ROADMAP.md); use
[ALPHA_INSTALL_VALIDATION.md](ALPHA_INSTALL_VALIDATION.md) for evidence boundaries.

The September 11 disposable environment was removed after qualification at the
user's request, including its VM, containers, images, HA volume and UI tunnel.
No owner setup had been completed. The localhost URL is no longer active;
the procedure below describes how to recreate the environment when needed.

## Choose the right level

| Environment | Valid evidence | Not established |
| --- | --- | --- |
| Fresh HA Container plus separate gateway container | Real HA onboarding, integration loading/config flow, empty inventory, restart persistence | Supervisor discovery, app repository installation, app lifecycle |
| Fresh HA OS VM | Full repository/app installation and Supervisor path, plus integration UI | Physical radio commissioning or safe valve operation without separate dry hardware tests |

HA Container runs Home Assistant without the Supervisor/app installation system;
HA OS includes it. A manually started gateway container is therefore not an
installed HA app, even when built from the app Dockerfile.
[HA installation types](https://www.home-assistant.io/installation/#about-installation-types),
[HA OS components](https://www.home-assistant.io/installation/linux/).

## Recommended first pass: dedicated Colima profile

Use a dedicated `rainpoint-alpha` profile, native `aarch64` and the `vz` VM backend
on supported macOS. Initial test budget: 2 vCPUs, 4 GiB RAM and 20 GiB disk; these
are starting allocations, not measured consumption or upstream minimums. Disable
Kubernetes, SSH-agent forwarding and automatic Docker-context switching. Explicitly
disable host mounts (`mounts: null`); the default includes the writable home
directory. Use named Docker volumes and copy only release/runtime files in.
Keep `network.address` and `network.hostAddresses` false; do not enable bridged
networking. These settings require inspection of the installed Colima version's
configuration before first start.
[Colima configuration](https://colima.run/docs/configuration/).

Profiles have separate VM/container data. Use `docker --context
colima-rainpoint-alpha ...` for every command rather than switching the user's
global Docker context. Stop the named profile when finished; keep its data until
evidence is captured.
[Colima profiles](https://colima.run/docs/profiles/).

Pre-download the selected HA image and build the gateway image before starting
the isolated runtime. Record the release tag, resolved image digest, architecture
and repository commit. Do not attach the running HA/gateway to an internet-enabled
network to fix dependency downloads; prepare dependencies in a separate image
build instead.

Create exactly one user-defined internal bridge, for example:

```bash
docker --context colima-rainpoint-alpha network create --internal rainpoint-alpha
docker --context colima-rainpoint-alpha volume create rainpoint-alpha-ha
docker --context colima-rainpoint-alpha volume create rainpoint-alpha-gateway
```

Attach only the two test containers to it. Docker internal networks omit the
default route and block traffic across networks, while allowing member containers
to communicate. They still allow access to their gateway and appropriately
configured host services: this is not an air gap against a host proxy. Do not
add host proxies, production tunnels, extra networks or host-gateway aliases.
[Docker internal networks](https://docs.docker.com/reference/cli/docker/network/create/#network-internal-mode---internal).
Container DNS names provide direct test-to-test addressing without LAN discovery.
[Docker user-defined bridges](https://docs.docker.com/engine/network/drivers/bridge/).

Create HA with the selected image using these constraints:

```text
--name rainpoint-alpha-ha
--network rainpoint-alpha
--publish 127.0.0.1:18123:8123
--mount source=rainpoint-alpha-ha,target=/config
--stop-timeout 60
--restart no
```

Only the HA UI may be published. Verify the macOS listener actually binds loopback
after Colima forwarding; visit `http://127.0.0.1:18123`, not `homeassistant.local`.
Use Docker Engine 28 or newer: older engines have a documented localhost-publish
L2 exposure issue. Do not enable direct routing.
[Docker port publishing](https://docs.docker.com/engine/network/port-publishing/).
The 60-second shutdown allowance follows HA guidance to protect its database.
[HA clean shutdown](https://www.home-assistant.io/installation/linux/#allow-time-for-a-clean-shutdown).

In the September 11 environment (Docker Engine 29.5.2), the internal-only
container retained the requested port binding but installed no published port
or NAT rule. The HA page worked inside the container. Keep the internal network:
use an inbound SSH local forward through the dedicated VM to the container's
inspected IP, not a second internet-enabled container network. Bind the forward
to `127.0.0.1:18123`, target only the test container's port 8123, and use the
VM-generated SSH configuration. Do not forward a host service back into HA.
Verify the macOS listener with `lsof -nP -iTCP:18123 -sTCP:LISTEN` and confirm
`docker ... exec rainpoint-alpha-ha ip route` still has no default route.
The container IP and generated SSH port may change after recreation; inspect
them again rather than embedding them in installation code.

The dedicated profile can be paused without deleting its data:

```bash
docker --context colima-rainpoint-alpha stop --time 60 rainpoint-alpha-ha
colima stop rainpoint-alpha
```

Stop the test-specific SSH forward as well. Do not use global Docker prune or
delete other profiles. This qualification environment is not a production
gateway install; creating the empty frontend does not configure an owner or an
integration connection. The automated Core test runs its own temporary gateway and cleans
that gateway up on completion.

For the gateway, override the image entrypoint to `python3`, use its existing
`/opt/rainpoint` working directory, mount only the fresh gateway volume at `/data`,
publish **no ports**, and run:

```text
-m rainpointd --transport network --host 0.0.0.0 --port 8787
--node-listen-port 0 --gateway-id isolated-alpha-test
--storage /data/rainpoint.sqlite3
```

Supply a newly generated high-entropy `RAINPOINT_REGISTRY_TOKEN` (32–256 bytes),
not a production credential. Keep it out of committed files and captured logs.
The intended endpoint is the test gateway's container name on port 8787,
authenticated with this token. Keep TLS enabled: plaintext `--insecure-development` exercises
a different transport. An empty volume and no catalog, firmware catalog,
`RAINPOINT_NODE_TOKENS`, serial device or replay fixtures produce the empty
gateway case. `--node-listen-port 0` prevents radio connections.
These project-specific controls come from
[the gateway CLI](../rainpointd_addon/rainpointd/__main__.py),
[gateway Dockerfile](../rainpointd_addon/Dockerfile) and
[integration client](../custom_components/rainpoint_local/api.py).

Source inspection found a qualification risk: the current manual setup form
accepts only host/port, while the client selects HTTPS only when given a token;
Supervisor discovery supplies that token, but the manual form does not.
Reproduce the real UI outcome before claiming standalone setup works. A
programmatic credential injection or plaintext harness cannot establish the
normal new-user path. This is a source-level observation, not a recorded browser
test result.
[Config flow](../custom_components/rainpoint_local/config_flow.py),
[YAML schema](../custom_components/rainpoint_local/__init__.py).

Do not use `--network host`, `--privileged`, USB/device mappings, Docker-socket
mounts, host D-Bus mounts, mDNS reflectors, or production backups/credentials.
This deliberately differs from HA's general-purpose container recipe, which
enables host networking and hardware access.
[HA container recipe](https://www.home-assistant.io/installation/linux/#install-home-assistant-container).

Before onboarding, inspect both containers and the network: one internal network
each, only the loopback HA port published, only fresh named volumes, no devices
or privilege, and no gateway radio listener. Verify routes/firewall inside the
test VM without probing the production HA address. If the UI cannot be reached,
inspect Colima's loopback forwarding; do not solve it with LAN/host networking.
Treat blocked cloud/discovery requests as expected; unexpected production device
discovery is a reason to stop the test. Record actual UI outcomes separately
from network configuration and package checks.

## Optional full app-repository test: HA OS VM

The current official macOS guide provides an Apple Silicon HA OS image and
requires at least 2 GiB RAM and 2 vCPUs. Budget 4 GiB RAM for this test and retain
the image's disk capacity. Crucially, its normal network instructions use a
**bridged adapter** to communicate with household devices. Do not use that
network setting for this qualification.
[HA OS on macOS](https://www.home-assistant.io/installation/macos/).

Proceed only with a verified VM network policy that blocks the household LAN,
VPN routes, IPv6 routes to production, multicast discovery and host relay paths.
Permit only loopback UI forwarding and narrowly scoped repository/image download
traffic as required. NAT alone is not proof of outbound isolation. If that
policy cannot be established, defer the VM pass rather than connecting it to
the house. Do not attach USB radios or restore a backup.

Use a new owner account, fresh app data, empty device catalog, network transport,
and `node_listen_port: 0` before starting the gateway; remove the app's host-port
mappings when supported because Supervisor-side communication is the test path.
Validate the repository URL flow and installation from the app store, then
Supervisor discovery and integration configuration. Local `/addons` source
testing is useful development evidence but is not proof of repository delivery.
[Official app repository flow](https://developers.home-assistant.io/docs/apps/repository/),
[official local app testing](https://developers.home-assistant.io/docs/apps/testing/).

Neither environment authorizes live RF pairing, flashing, irrigation commands,
or production HA changes. Those remain separate dry-hardware acceptance work.
