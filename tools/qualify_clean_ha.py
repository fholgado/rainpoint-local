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
from types import SimpleNamespace
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rainpointd_addon"))
from rainpointd.secure_transport import client_context


async def qualify_notifications(hass, entry) -> None:
    """Check real HA notification storage using fabricated observation snapshots.

    The gateway stays empty. No device registration, actuator call, mobile
    service or live radio is involved. This proves backend delivery, not pixels.
    """
    from homeassistant.components import persistent_notification
    from homeassistant.helpers.update_coordinator import UpdateFailed

    coordinator = hass.data["rainpoint_local"][entry.entry_id]
    await coordinator.async_stop_event_listener()
    forwarded = []
    unsubscribe = hass.bus.async_listen("rainpoint_local_watering_notification",
                                       lambda event: forwarded.append(event.data))

    def notifications():
        messages = []
        connection = SimpleNamespace(send_message=messages.append)
        persistent_notification.websocket_get_notifications(
            hass, connection, {"id": 1, "type": "persistent_notification/get"})
        assert messages[-1]["success"]
        return {n["notification_id"]: n for n in messages[-1]["result"]}

    try:
        for model in ("HTV145FRF", "HTV405FRF"):
            device_id = f"qualification-{model.lower()}"
            run_id = f"rainpoint_local_{entry.entry_id}_{device_id}_run"
            problem_id = f"rainpoint_local_{entry.entry_id}_{device_id}_problem"

            async def observe(watering, **state):
                coordinator.async_set_updated_data({device_id: {
                    "model": model, "name": "Qualification valve", "state": {
                        "is_watering": watering, **state}}})
                await hass.async_block_till_done()

            await observe(False)
            await observe(False, rf_control_transaction_state="waiting_for_confirmation")
            assert run_id not in notifications()
            values = {"active_zone": 1, "rf_control_transaction_id": "synthetic-run",
                      "rf_control_transaction_state": "confirmed",
                      "rf_control_transaction_duration_seconds": 1260}
            await observe(True, **values)
            assert "21 minutes" in notifications()[run_id]["message"]
            assert forwarded[-1]["notification_id"] == run_id
            count = len(forwarded)
            await observe(True, **values)
            await observe(None)
            coordinator.async_set_update_error(UpdateFailed("synthetic unavailable snapshot"))
            await hass.async_block_till_done()
            assert len(forwarded) == count
            assert notifications()[run_id]["title"].endswith(": watering")
            await observe(False)
            assert notifications()[run_id]["title"].endswith("watering stopped")
            await observe(False, rf_control_transaction_id="synthetic-failure",
                          rf_control_transaction_state="failed")
            assert "did not confirm" in notifications()[problem_id]["message"]
            count = len(forwarded)
            await observe(False, rf_control_transaction_id="synthetic-failure",
                          rf_control_transaction_state="failed")
            await observe(False)
            assert len(forwarded) == count
            assert problem_id in notifications()  # Recovery does not erase failure.
            await observe(True, rf_control_overdue=True)
            assert "expected stop" in notifications()[problem_id]["message"]
            await hass.services.async_call("persistent_notification", "dismiss",
                {"notification_id": problem_id}, blocking=True)
            assert problem_id not in notifications()
    finally:
        unsubscribe()
        coordinator.async_set_updated_data({})
        persistent_notification.async_dismiss_all(hass)


async def qualify_manual_setup(hass, port: int, token: str) -> None:
    """Exercise the public form and real TLS connection, not discovery injection."""
    from homeassistant.helpers import selector

    flow = await hass.config_entries.flow.async_init(
        "rainpoint_local", context={"source": "user"})
    assert flow["type"] == "form" and flow["step_id"] == "user"
    schema = flow["data_schema"].schema
    secret = next(value for key, value in schema.items() if str(key) == "registry_write_token")
    assert isinstance(secret, selector.TextSelector)
    assert secret.config["type"] == selector.TextSelectorType.PASSWORD
    request = {"host": "127.0.0.1", "port": port, "registry_write_token": ""}
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], request)
    assert result["type"] == "form" and result["errors"]["base"] == "invalid_auth"
    request["registry_write_token"] = "too-short"
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], request)
    assert result["type"] == "form" and result["errors"]["base"] == "invalid_auth"
    request["registry_write_token"] = secrets.token_urlsafe(32)
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], request)
    assert result["type"] == "form" and result["errors"]["base"] == "cannot_connect"
    assert not hass.config_entries.async_entries("rainpoint_local")
    request["registry_write_token"] = token
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], request)
    assert result["type"] == "create_entry", result.get("type")
    entry = result["result"]
    await hass.async_block_till_done()
    assert entry.state.value == "loaded"
    assert entry.data["registry_write_token"] == token
    duplicate = await hass.config_entries.flow.async_init(
        "rainpoint_local", context={"source": "user"})
    duplicate = await hass.config_entries.flow.async_configure(duplicate["flow_id"], request)
    assert duplicate["type"] == "abort" and duplicate["reason"] == "already_configured"
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state.value == "loaded"
    assert entry.data["registry_write_token"] == token
    assert (await hass.config_entries.async_remove(entry.entry_id))["require_restart"] is False


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
        await qualify_notifications(hass, entry)
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
        await qualify_manual_setup(hass, port, token)
        print("PASS: real HA Core TLS setup, duplicate discovery, model menus, "
              "no-radio feedback, reload/removal, manual TLS credentials and "
              "notification delivery/deduplication/dismissal; no RF commands")
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
