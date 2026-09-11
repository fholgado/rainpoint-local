#!/usr/bin/env python3
"""Exercise real HA Core setup against an empty TLS gateway in an isolated container.

No household config, radio, or valve is used. This does not emulate Supervisor,
install HACS, or claim physical pairing/rendered-frontend qualification.
"""
import asyncio
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rainpointd_addon"))
from rainpointd.secure_transport import client_context


async def qualify(config_dir: Path, port: int, token: str) -> None:
    from homeassistant.core import HomeAssistant
    from homeassistant import bootstrap, loader
    from homeassistant.helpers.service_info.hassio import HassioServiceInfo

    hass = HomeAssistant(str(config_dir))
    try:
        loader.async_setup(hass)
        assert await bootstrap.async_from_config_dict({"persistent_notification": {}}, hass) is hass
        await hass.async_start()
        discovery = HassioServiceInfo(
            name="RainPoint clean-install test", slug="local_rainpointd", uuid="clean-install",
            config={"host": "127.0.0.1", "port": port,
                    "registry_write_token": token, "gateway_id": "clean-install"})
        flow = await hass.config_entries.flow.async_init(
            "rainpoint_local", context={"source": "hassio"}, data=discovery)
        assert flow["type"] == "form" and flow["step_id"] == "hassio_confirm"
        result = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
        assert result["type"] == "create_entry", result.get("type")
        entry = result["result"]
        await hass.async_block_till_done()
        assert entry.state.value == "loaded", entry.state
        assert entry.data["registry_write_token"] == token
        assert "persistent_notification" in hass.config.components
        duplicate = await hass.config_entries.flow.async_init(
            "rainpoint_local", context={"source": "hassio"}, data=discovery)
        assert duplicate["type"] == "abort" and duplicate["reason"] == "already_configured"
        assert len(hass.config_entries.async_entries("rainpoint_local")) == 1
        options = await hass.config_entries.options.async_init(entry.entry_id)
        assert options["type"] == "menu"
        assert "add_device" in options["menu_options"]
        assert "authenticate_gateway" not in options["menu_options"]
        categories = await hass.config_entries.options.async_configure(
            options["flow_id"], {"next_step_id": "add_device"})
        assert set(categories["menu_options"]) == {"add_sensor", "add_valve"}
        models = await hass.config_entries.options.async_configure(
            categories["flow_id"], {"next_step_id": "add_valve"})
        assert models["type"] == "form" and models["step_id"] == "add_valve"
        schema = models["data_schema"].schema
        validator = next(iter(schema.values()))
        assert {"htv145_auto_candidate_v1", "htv405_auto_candidate_v1"} <= set(validator.container)
        no_node = await hass.config_entries.options.async_configure(
            models["flow_id"], {"profile_id": "htv145_auto_candidate_v1"})
        assert no_node["errors"]["base"] == "no_pairing_node"
        hass.config_entries.options.async_abort(no_node["flow_id"])
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state.value == "loaded"
        removed = await hass.config_entries.async_remove(entry.entry_id)
        assert removed["require_restart"] is False
        assert not hass.config_entries.async_entries("rainpoint_local")
        print("PASS: real HA Core TLS setup, duplicate discovery, model menus, "
              "no-radio feedback, reload and removal; no RF commands")
    finally:
        await hass.async_stop(force=True)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rainpoint-ha-clean-") as directory:
        root = Path(directory)
        config = root / "ha"
        shutil.copytree(ROOT / "custom_components/rainpoint_local",
                        config / "custom_components/rainpoint_local")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        token = secrets.token_urlsafe(32)
        import os
        environment = dict(os.environ, RAINPOINT_REGISTRY_TOKEN=token)
        environment.pop("RAINPOINT_NODE_TOKENS", None)
        environment.pop("RAINPOINT_CLAIM_CODE", None)
        process = subprocess.Popen(
            [sys.executable, "-m", "rainpointd", "--transport", "network",
             "--host", "127.0.0.1", "--port", str(port), "--node-listen-port", "0",
             "--gateway-id", "clean-install", "--storage", str(root / "gateway.sqlite3")],
            cwd=ROOT / "rainpointd_addon", env=environment,
            stdout=subprocess.DEVNULL)
        try:
            import time
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("isolated gateway exited")
                try:
                    with urllib.request.urlopen(f"https://127.0.0.1:{port}/health",
                            context=client_context(token), timeout=1):
                        break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError("isolated gateway startup timed out")
            asyncio.run(qualify(config, port, token))
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
