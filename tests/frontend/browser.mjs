// Render the shipped panel against isolated HA UI responses, never live RF.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import http from "node:http";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.RAINPOINT_PLAYWRIGHT_MODULE || "playwright");
const root = new URL("../../custom_components/rainpoint_local/", import.meta.url);
const strings = JSON.parse(await readFile(new URL("strings.json", root), "utf8")).options;
const server = http.createServer(async (request, response) => {
  const path = new URL(request.url, "http://localhost").pathname;
  if (path === "/") {
    response.setHeader("Content-Type", "text/html");
    response.end('<!doctype html><html><body><rainpoint-device-panel></rainpoint-device-panel><script type="module" src="/panel.js"></script></body></html>');
  } else if (["/panel.js", "/wizard.js"].includes(path)) {
    response.setHeader("Content-Type", "text/javascript");
    response.end(await readFile(new URL(`frontend${path}`, root)));
  } else { response.statusCode = 404; response.end(); }
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const browser = await chromium.launch({ headless: true,
  ...(process.env.RAINPOINT_BROWSER ? { executablePath: process.env.RAINPOINT_BROWSER } : {}) });
const page = await browser.newPage({ viewport: { width: 1100, height: 850 } });
const errors = [];
page.on("pageerror", error => errors.push(error.message));
try {
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  await page.waitForFunction(() => customElements.get("rainpoint-device-panel"));
  await page.evaluate(strings => {
    const state = window.fixture = { calls: [], devices: [], count: 0, stage: "", finish: false, fail: false };
    const models = { soil: "Soil moisture sensor", single: "Single-zone valve", four: "Four-zone valve" };
    const make = (type, step_id, extra = {}) => state.result = { type, step_id, flow_id: `flow-${state.count}`, ...extra };
    const form = (step, fields) => make("form", step, { data_schema: fields });
    const profileForm = step => form(step, [{ name: "profile_id", required: true, type: "select",
      options: Object.entries(models).filter(([key]) => step === "add_sensor" ? key === "soil" : key !== "soil") }]);
    const radioForm = () => form("pair_device", [{ name: "node_id", required: true, type: "select", options: [["node-a", "Nearby garden radio"]], default: "node-a" },
      { name: "duration_seconds", required: true, type: "integer", default: 120 }]);
    const hass = {
      config: { version: "2026.9.1" }, language: "en",
      async callWS(data) {
        state.calls.push(data);
        if (data.type === "rainpoint_local/wizard_inventory") return {
          gateways: [{ entry_id: "gateway-a", title: "Custom garden gateway" }], devices: state.devices,
          areas: [{ area_id: "garden", name: "Garden" }], strings,
        };
        if (data.type === "rainpoint_local/wizard_cancel") {
          if (state.failCancel) throw new Error("offline");
          return { closed: true, stop_requested: state.result?.type === "show_progress" };
        }
        if (data.type === "config/device_registry/remove") {
          if (state.failRemove) throw new Error("active valve");
          state.devices = state.devices.filter(d => d.id !== data.device_id);
          return null;
        }
        throw new Error("Unexpected websocket operation");
      },
      async callApi(method, path, data) {
        state.calls.push({ method, path, data });
        if (method === "GET") {
          if (state.fail) return make("abort", undefined, { reason: "pairing_timeout" });
          if (state.finish && state.result.step_id === "pairing_progress") {
            state.finish = false;
            return form("device_details", [{ name: "name", required: true, type: "string", default: "New device" },
              { name: "area", selector: { area: {} } }]);
          }
          if (state.finish && state.result.step_id === "commission_progress") {
            state.finish = false;
            return make("form", "commission_result", { data_schema: [], description_placeholders: { result: "Valve setup complete", reason: "ready" } });
          }
          return state.result;
        }
        if (data.handler) { state.count++; state.fail = false; return make("menu", "init", { menu_options: ["add_device"] }); }
        if (data.next_step_id === "add_device") return make("menu", "add_device", { menu_options: ["add_sensor", "add_valve"] });
        if (["add_sensor", "add_valve"].includes(data.next_step_id)) return profileForm(data.next_step_id);
        if (data.profile_id) { state.model = data.profile_id; return radioForm(); }
        if (data.node_id) return make("menu", "pairing_review", { menu_options: ["start_pairing", "change_pairing_model", "change_pairing_radio"],
          description_placeholders: { device_name: models[state.model], node_name: "Nearby garden radio", duration_seconds: String(data.duration_seconds) } });
        if (data.next_step_id === "change_pairing_radio") return radioForm();
        if (data.next_step_id === "start_pairing") return make("show_progress", "pairing_progress", { progress_action: "wait_for_device",
          description_placeholders: { node_name: "Nearby garden radio", device_name: models[state.model], duration_seconds: "300" } });
        if (data.name) {
          state.devices.push({ id: `device-${state.count}`, name: data.name, model: models[state.model], area_id: data.area });
          if (state.model === "single") return make("menu", "commission_review", { menu_options: ["commission_start", "commission_later", "verify_valve"] });
          return make("create_entry");
        }
        if (data.next_step_id === "commission_start") return form("commission_start", []);
        if (state.result.step_id === "commission_start") return make("show_progress", "commission_progress", { progress_action: "commission_wait" });
        if (state.result.step_id === "commission_result") return make("create_entry");
        throw new Error("Unexpected flow transition");
      },
    };
    document.querySelector("rainpoint-device-panel").hass = hass;
  }, strings);
  const button = name => page.getByRole("button", { name, exact: true });
  const dialog = () => page.getByRole("dialog");
  async function start(model) {
    await button("Add a RainPoint device").click();
    await button(model === "soil" ? "Sensors" : "Valves").click();
    await page.getByLabel("Model", { exact: true }).selectOption(model);
    await button("Next").click();
    await page.getByLabel("Pairing window (seconds)").fill("300");
    await button("Next").click();
  }
  for (const [model, name] of [["soil", "Test soil"], ["four", "Four-zone test"], ["single", "Single-zone test"]]) {
    await start(model);
    await button("Back").click();
    assert.equal(await page.getByLabel("Pairing window (seconds)").inputValue(), "300");
    await button("Next").click();
    if (process.env.RAINPOINT_UI_SCREENSHOT && model === "soil") await page.screenshot({ path: process.env.RAINPOINT_UI_SCREENSHOT });
    await button("Start pairing").click();
    await page.evaluate(() => { window.fixture.finish = true; });
    await page.getByLabel("Name", { exact: true }).fill(name);
    await page.getByLabel("Area", { exact: true }).selectOption("garden");
    await button("Back").click();
    await page.getByRole("heading", { name: "Pairing accepted" }).waitFor();
    await button("Next").click();
    assert.equal(await page.getByLabel("Name", { exact: true }).inputValue(), name);
    await button("Save device").click();
    if (model === "single") {
      await button("Finish setup").click();
      await button("Next").click();
      await page.evaluate(() => { window.fixture.finish = true; });
      await page.getByRole("heading", { name: "Valve setup complete" }).waitFor();
      await button("Next").click();
    }
    await button("Back to devices").click();
    await page.locator(".row").filter({ hasText: name }).waitFor();
  }
  // Failure is visible, and Back returns to settings without automatically arming.
  await start("soil");
  await button("Start pairing").click();
  await page.evaluate(() => { window.fixture.fail = true; });
  await page.getByRole("heading", { name: "Pairing did not finish" }).waitFor();
  await button("Back").click();
  await page.getByLabel("Local radio node").waitFor();
  await button("Close").click();
  // Remove rejection retains the row, successful removal closes the modal.
  await page.evaluate(() => { window.fixture.failRemove = true; });
  await button("Remove").first().click();
  await button("Remove device").click();
  await dialog().getByText(/Removal was not confirmed/).waitFor();
  await page.evaluate(() => { window.fixture.failRemove = false; });
  await button("Remove device").click();
  await page.waitForFunction(() => !document.querySelector("rainpoint-device-panel").shadowRoot.querySelector('[role="dialog"]'));
  assert.equal(await button("Remove").count(), 2);
  // Mobile layout stays inside the viewport.
  await page.setViewportSize({ width: 390, height: 844 });
  await start("four");
  const box = await dialog().boundingBox();
  assert.ok(box.x >= 0 && box.width <= 390);
  await button("Close").click();
  const calls = await page.evaluate(() => window.fixture.calls);
  assert.equal(calls.filter(c => c.data?.next_step_id === "start_pairing").length, 4);
  assert.equal(calls.some(c => /valve\/open|valve\/close/.test(c.path || "")), false);
  assert.deepEqual(errors, []);
  console.log("PASS: rendered sensor/both-valve wizard, preserved Back/Next, progress/failure, owner setup, removal and mobile layout; isolated UI responses only");
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
