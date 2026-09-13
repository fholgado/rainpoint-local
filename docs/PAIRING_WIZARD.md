# Device setup wizard

Available in integration **0.18.2 (unreleased)**. Alpha 1 retains the native HA
options screens. No gateway or radio firmware change is required for this UI.

Open **RainPoint devices** in HA's sidebar as an administrator. Choose your custom
local gateway if you have more than one, then **Add a RainPoint device**.

1. Choose Sensors or Valves, then a supported model from the gateway's catalog.
2. Select the closest custom local radio node and a listening window.
3. Review. **Back** changes settings; **Start pairing** is the first action that arms a radio.
4. Follow the device instructions. The screen advances through detection,
   exchange, identity confirmation and finalization without another Next click.
5. Set the name/area and save. If shown, finish valve radio setup; this does not water.

Back preserves selections. After RF acceptance, Back reviews the accepted
identity; it does not undo physical pairing. After saving a device, Back returns
to the list without removing it. The single-zone valve's radio setup remains a
separate step and can also be resumed through the native **Finish valve setup** menu.

**Stop and close** cancels only this flow's pairing/setup request. A gateway
cancellation response is not proof the radio has received it; its bounded window
still expires automatically. If cancellation cannot be confirmed, the wizard
stays open with feedback and a retry path. Reloading the browser resumes the
retained HA flow; it never repeats Start pairing automatically.

Use **Remove** beside a device and confirm. Success returns to the refreshed list;
failure keeps the device visible. Removal does not factory-reset the hardware.
This navigation applies to the new panel, not HA's separate native device page.

Gateway discovery, BOOT-button radio adoption and native options remain available
under **Devices & services → RainPoint Local**. The custom panel never receives
the gateway's management credential. It uses HA's existing options-flow and
device-removal operations, plus an administrator-only, flow-scoped cancellation
adapter; pairing/RF builders are unchanged.

## Verification

- `node --test tests/frontend/wizard.test.mjs`: navigation, no re-arming on Back
  or refresh, duplicate-click exclusion and cancellation failure.
- `node tests/frontend/browser.mjs` with Playwright installed: rendered sensor,
  single-/four-zone flows, progress/failure, removal and mobile layout against
  isolated UI responses. These are not RF pairing tests.
- `tools/qualify_clean_ha.py`: real HA panel registration, native schemas,
  credential exclusion, unarmed cancellation, reload and removal.

Physical acceptance and deployment status remain in the [roadmap](../PROJECT_ROADMAP.md).
HA's [options-flow implementation](https://github.com/home-assistant/core/blob/2026.9.1/homeassistant/components/config/config_entries.py)
and [device-removal implementation](https://github.com/home-assistant/core/blob/2026.9.1/homeassistant/components/config/device_registry.py)
define the native operations reused here.
