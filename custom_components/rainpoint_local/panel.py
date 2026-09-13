"""Admin frontend over the existing options flow; no second RF state machine."""
from __future__ import annotations

import json
from pathlib import Path

import voluptuous as vol
from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.data_entry_flow import UnknownFlow
from homeassistant.helpers import area_registry as ar, device_registry as dr

from .api import RainPointLocalError
from .const import CONF_TOKEN, DOMAIN

PANEL_KEY = f"{DOMAIN}_panel"
PANEL_PATH = "rainpoint-local"
STATIC_PATH = "/rainpoint_local/panel"


async def async_setup_panel(hass):
    """Register assets once; restore the panel after an entry reload."""
    if PANEL_KEY not in hass.data:
        strings = await hass.async_add_executor_job(
            lambda: json.loads(Path(__file__).with_name("strings.json").read_text())["options"])
        await hass.http.async_register_static_paths([
            StaticPathConfig(STATIC_PATH, str(Path(__file__).with_name("frontend")), False)])
        websocket_api.async_register_command(hass, websocket_inventory)
        websocket_api.async_register_command(hass, websocket_cancel)
        hass.data[PANEL_KEY] = {"strings": strings, "registered": False}
    if hass.data[PANEL_KEY]["registered"]:
        return
    await panel_custom.async_register_panel(
        hass, frontend_url_path=PANEL_PATH, webcomponent_name="rainpoint-device-panel",
        sidebar_title="RainPoint devices", sidebar_icon="mdi:sprout",
        module_url=f"{STATIC_PATH}/panel.js?v=0.18.2", require_admin=True)
    hass.data[PANEL_KEY]["registered"] = True


def async_remove_panel(hass):
    """Remove the navigation item when the last gateway is unloaded."""
    frontend.async_remove_panel(hass, PANEL_PATH)
    hass.data[PANEL_KEY]["registered"] = False


def inventory(hass, selected=None):
    """Return only entry-scoped display data, never connection credentials."""
    entries = hass.config_entries.async_entries(DOMAIN)
    result = {
        "gateways": [{"entry_id": e.entry_id, "title": e.title} for e in entries],
        "devices": [], "strings": hass.data[PANEL_KEY]["strings"],
        "areas": [{"area_id": a.id, "name": a.name} for a in ar.async_get(hass).async_list_areas()],
    }
    entry = next((e for e in entries if e.entry_id == selected), None)
    if entry is not None and (coordinator := hass.data.get(DOMAIN, {}).get(selected)):
        for device in dr.async_entries_for_config_entry(dr.async_get(hass), selected):
            local = next((identifier[1] for identifier in device.identifiers
                          if identifier[0] == DOMAIN), None)
            observation = (coordinator.data or {}).get(local)
            # Radio and gateway removal remain in their native management flows.
            if observation is not None and "forget" in observation.get("capabilities", []):
                result["devices"].append({
                    "id": device.id, "name": device.name_by_user or device.name or local,
                    "model": device.model, "area_id": device.area_id,
                    "reporting": observation.get("reporting"),
                })
    return result


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "rainpoint_local/wizard_inventory",
    vol.Optional("entry_id"): str,
})
@websocket_api.async_response
async def websocket_inventory(hass, connection, msg):
    connection.send_result(msg["id"], inventory(hass, msg.get("entry_id")))


async def cancel_flow(hass, entry_id, flow_id):
    """Stop only this options flow's pairing/setup before removing the flow.

    A successful gateway stop is a cancellation request, not proof that the
    radio has received it. The existing bounded RF window still applies.
    On network failure retain the flow so the UI can retry or inspect progress.
    """
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ValueError("unknown gateway")
    manager = hass.config_entries.options
    try:
        flow = manager.async_get(flow_id)
    except UnknownFlow:
        return {"closed": True, "stop_requested": False}
    if flow["handler"] != entry_id:
        raise ValueError("flow belongs to a different gateway")
    context = flow.get("context", {})
    coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
    command_id = context.get("rainpoint_pairing_command_id")
    device_id = context.get("rainpoint_commission_device_id")
    if (command_id or device_id) and coordinator is None:
        raise ValueError("gateway is not loaded")
    token = entry.data.get(CONF_TOKEN)
    if device_id:
        await coordinator.client.commission_valve(token, device_id, "cancel",
            pairing_command_id=context.get("rainpoint_commission_command_id"))
    if command_id:
        await coordinator.client.stop_pairing(token, command_id=command_id)
    try:
        manager.async_abort(flow_id)
    except UnknownFlow:
        pass  # Completion may race a successful cancellation request.
    return {"closed": True, "stop_requested": bool(command_id or device_id)}


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "rainpoint_local/wizard_cancel",
    vol.Required("entry_id"): str, vol.Required("flow_id"): str,
})
@websocket_api.async_response
async def websocket_cancel(hass, connection, msg):
    try:
        result = await cancel_flow(hass, msg["entry_id"], msg["flow_id"])
    except (RainPointLocalError, ValueError):
        connection.send_error(msg["id"], "cancel_failed",
            "Unable to close this flow. Check the gateway and retry; its RF window remains bounded.")
    else:
        connection.send_result(msg["id"], result)
