import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
const source = await readFile(new URL("../../custom_components/rainpoint_local/frontend/wizard.js", import.meta.url));
const { WizardFlow } = await import(`data:text/javascript;base64,${source.toString("base64")}`);

function harness() {
  let id = 0;
  let result;
  const calls = [];
  const hass = {
    async callApi(method, path, data) {
      calls.push({ method, path, data });
      if (method === "GET") return result;
      if (!data || "handler" in data) result = { type: "menu", step_id: "init", flow_id: `${++id}`, menu_options: ["add_device"] };
      else if (data.next_step_id === "add_device") result = { ...result, step_id: "add_device", menu_options: ["add_sensor", "add_valve"] };
      else if (["add_sensor", "add_valve"].includes(data.next_step_id)) result = { ...result, type: "form", step_id: data.next_step_id };
      else if (data.profile_id || data.next_step_id === "change_pairing_radio") result = { ...result, type: "form", step_id: "pair_device" };
      else if (data.node_id) result = { ...result, type: "menu", step_id: "pairing_review" };
      else if (data.next_step_id === "start_pairing") result = { ...result, type: "show_progress", step_id: "pairing_progress" };
      return result;
    },
    async callWS(data) { calls.push(data); return { closed: true, stop_requested: result.type === "show_progress" }; },
  };
  const storage = new Map();
  const flow = new WizardFlow(hass, () => {}, { setItem: (k,v) => storage.set(k,v), getItem: k => storage.get(k), removeItem: k => storage.delete(k) });
  return { flow, calls, hass, storage };
}
async function review(flow) {
  await flow.begin("gateway-a");
  await flow.submit({ next_step_id: "add_valve" });
  await flow.submit({ profile_id: "catalog-owned-profile" });
  await flow.submit({ node_id: "nearby-node", duration_seconds: 300 });
}
test("review/back never arms and preserves selections", async () => {
  const { flow, calls } = harness();
  await review(flow);
  await flow.back();
  assert.equal(flow.result.step_id, "pair_device");
  assert.equal(flow.drafts.pair_device.duration_seconds, 300);
  await flow.back();
  assert.equal(flow.result.step_id, "add_valve");
  await flow.back();
  assert.equal(flow.result.step_id, "add_device");
  assert.equal(calls.filter(c => c.data?.next_step_id === "start_pairing").length, 0);
});
test("progress Back stops owned flow then returns to radio without rearming", async () => {
  const { flow, calls } = harness();
  await review(flow);
  await flow.submit({ next_step_id: "start_pairing" });
  const armed = flow.result.flow_id;
  await flow.back();
  assert.equal(flow.result.step_id, "pair_device");
  assert.ok(calls.some(c => c.type === "rainpoint_local/wizard_cancel" && c.flow_id === armed));
  assert.equal(calls.filter(c => c.data?.next_step_id === "start_pairing").length, 1);
});
test("cancellation failure keeps current flow and surfaces feedback", async () => {
  const { flow, hass } = harness();
  await review(flow);
  await flow.submit({ next_step_id: "start_pairing" });
  hass.callWS = async () => { throw new Error("offline"); };
  await flow.back();
  assert.equal(flow.result.step_id, "pairing_progress");
  assert.match(flow.error, /could not be confirmed/);
});
test("double click cannot dispatch a second arm request", async () => {
  const { flow, calls } = harness();
  await review(flow);
  await Promise.all([flow.submit({ next_step_id: "start_pairing" }), flow.submit({ next_step_id: "start_pairing" })]);
  assert.equal(calls.filter(c => c.data?.next_step_id === "start_pairing").length, 1);
});
test("acceptance review does not repeat pairing", async () => {
  const { flow, calls } = harness();
  flow.result = { type: "form", step_id: "device_details", flow_id: "accepted" };
  await flow.back();
  assert.equal(flow.successReview, true);
  await flow.submit({});
  assert.equal(flow.successReview, false);
  assert.equal(calls.length, 0);
});
test("refresh recovery only gets the retained flow, never repeats arming", async () => {
  const { flow, calls, hass, storage } = harness();
  await review(flow);
  await flow.submit({ next_step_id: "start_pairing" });
  const next = new WizardFlow(hass, () => {}, { getItem: k => storage.get(k), setItem: (k,v) => storage.set(k,v), removeItem: k => storage.delete(k) });
  calls.length = 0;
  await next.restore();
  assert.equal(next.result.step_id, "pairing_progress");
  assert.deepEqual(calls.map(c => c.method), ["GET"]);
});
