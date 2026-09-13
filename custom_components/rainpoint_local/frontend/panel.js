import { WizardFlow } from "./wizard.js";

function element(tag, text, attributes = {}) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  for (const [key, value] of Object.entries(attributes)) {
    if (value !== undefined && value !== null) node.setAttribute(key, value);
  }
  return node;
}
function interpolate(text = "", values = {}) {
  return text.replace(/\{([^}]+)\}/g, (_, key) => values[key] ?? `{${key}}`);
}

class RainPointDevicePanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.inventory = { gateways: [], devices: [], areas: [], strings: {} };
    this.loading = false;
    this.message = "";
  }
  set hass(hass) {
    this._hass = hass;
    if (this.flow) this.flow.hass = hass;
    if (!this.flow && hass) {
      this.flow = new WizardFlow(hass, () => this.render());
      this.load().then(() => this.flow.restore());
    }
  }
  connectedCallback() {
    this.timer = setInterval(() => {
      if (this.flow?.result?.type === "show_progress" && !this.flow.busy) this.flow.refresh();
    }, 1500);
  }
  disconnectedCallback() {
    clearInterval(this.timer);
    // Do not issue a new request on unload. HA retains the bounded flow and the
    // browser can resume its identity; no command is replayed on return.
  }
  async load(entryId = this.selected) {
    this.loading = true;
    this.render();
    try {
      this.inventory = await this._hass.callWS({ type: "rainpoint_local/wizard_inventory",
        ...(entryId ? { entry_id: entryId } : {}) });
      if (!entryId && this.inventory.gateways.length) {
        this.selected = this.inventory.gateways[0].entry_id;
        this.inventory = await this._hass.callWS({ type: "rainpoint_local/wizard_inventory", entry_id: this.selected });
      } else this.selected = entryId;
    } catch { this.message = "Unable to load RainPoint devices. Check your HA connection and refresh."; }
    this.loading = false;
    this.render();
  }
  button(label, action, primary = false) {
    const button = element("button", label, { type: "button", class: primary ? "primary" : "" });
    button.disabled = this.loading || this.flow?.busy;
    button.addEventListener("click", action);
    return button;
  }
  async leave(back = false) {
    await (back ? this.flow.back() : this.flow.close());
    if (!this.flow.result) await this.load(this.flow.entryId || this.selected);
  }
  async removeDevice(device) {
    this.loading = true;
    this.render();
    try {
      const [year, month] = this._hass.config.version.split(".").map(Number);
      const modern = year > 2026 || (year === 2026 && month >= 8);
      await this._hass.callWS({ type: modern ? "config/device_registry/remove" : "config/device_registry/remove_config_entry",
        device_id: device.id, ...(modern ? {} : { config_entry_id: this.selected }) });
      this.removing = null;
      this.message = `${device.name} removed. This does not factory-reset the physical device.`;
      await this.load(); // Return to the list, never a deleted device route.
    } catch {
      this.message = "Removal was not confirmed. The device remains listed; check the gateway and retry.";
      this.loading = false;
      this.render();
    }
  }
  render() {
    if (!this.shadowRoot || !this.flow) return;
    // Save typed values before polling/busy renders; never replace them with defaults.
    const previous = this.shadowRoot.querySelector("form");
    if (previous && this.flow.result?.step_id === previous.dataset.step) this.saveInputs(previous);
    const focused = this.shadowRoot.activeElement;
    const focusId = focused?.id;
    const focusLabel = focused?.tagName === "BUTTON" ? focused.textContent : null;
    this.shadowRoot.replaceChildren();
    const style = element("style");
    style.textContent = `
      :host{display:block;height:100%;overflow:auto;color:var(--primary-text-color,#202124);background:var(--primary-background-color,#fafafa);font-family:var(--paper-font-body1_-_font-family,system-ui)}
      main{max-width:880px;margin:auto;padding:24px}header,.row,footer{display:flex;gap:12px;align-items:center;justify-content:space-between}h1{font-size:24px}h2{font-size:21px;margin-top:0}p{line-height:1.5}a{color:var(--primary-color,#03a9f4)}
      button,input,select{font:inherit;box-sizing:border-box}button{padding:10px 16px;min-height:44px;cursor:pointer;border:1px solid var(--divider-color,#aaa);border-radius:8px;background:var(--card-background-color,#fff);color:inherit}button.primary{background:var(--primary-color,#0078a8);color:var(--text-primary-color,#fff);border-color:transparent}button:disabled{opacity:.5;cursor:default}button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid var(--primary-color,#0078a8);outline-offset:2px}
      .row{padding:16px 0;border-bottom:1px solid var(--divider-color,#ddd)}small{display:block;margin-top:4px;color:var(--secondary-text-color,#555)}.actions{display:flex;gap:8px;flex-wrap:wrap}.overlay{position:fixed;inset:0;background:#0007;display:grid;place-items:center;z-index:5;padding:16px}.dialog{background:var(--card-background-color,#fff);border-radius:16px;max-width:560px;width:100%;max-height:calc(100vh - 32px);overflow:auto;box-sizing:border-box;padding:24px}footer{margin-top:24px;flex-wrap:wrap}.steps{font-size:13px;color:var(--secondary-text-color,#555);margin-bottom:16px}.notice{padding:12px;border-left:4px solid var(--primary-color,#03a9f4);background:var(--secondary-background-color,#eee);white-space:pre-line}.error{border-color:var(--error-color,#db4437)}label{display:block;margin:16px 0 6px}input,select{width:100%;padding:12px;border-radius:6px;border:1px solid var(--divider-color,#aaa);color:inherit;background:var(--card-background-color,#fff)}.menus button{display:block;width:100%;text-align:left;margin:10px 0}.progress{padding:16px 0;font-weight:600}.fields-error{color:var(--error-color,#db4437)}@media(max-width:500px){main{padding:12px}.dialog{padding:20px}header{align-items:flex-start;flex-direction:column}.row{gap:8px}.actions{gap:6px}}
    `;
    this.shadowRoot.append(style);
    const main = element("main");
    const header = element("header");
    header.append(element("h1", "RainPoint devices"), this.button("Refresh", () => this.load()));
    main.append(header);
    const manage = element("a", "Gateway and radio setup in Devices & services", { href: "/config/integrations/integration/rainpoint_local" });
    main.append(manage);
    if (this.inventory.gateways.length > 1) {
      const selector = element("select", undefined, { "aria-label": "Custom local gateway" });
      for (const gateway of this.inventory.gateways) selector.append(element("option", gateway.title, { value: gateway.entry_id }));
      selector.value = this.selected;
      selector.disabled = this.loading || !!this.flow.result;
      selector.onchange = () => this.load(selector.value);
      main.append(selector);
    }
    if (this.message) main.append(element("p", this.message, { class: "notice", role: "status" }));
    const add = this.button("Add a RainPoint device", () => this.flow.begin(this.selected), true);
    add.disabled ||= !this.selected || !!this.flow.result;
    main.append(element("p", "Pair supported sensors and valves with your custom local radio nodes."), add);
    if (!this.inventory.gateways.length && !this.loading) main.append(element("p", "Set up the RainPoint Local integration first."));
    for (const device of this.inventory.devices) {
      const row = element("div", undefined, { class: "row" });
      const label = element("div", device.name);
      label.append(element("small", `${device.model || "RainPoint device"}${device.reporting === false ? " · Report stale" : ""}`));
      const actions = element("div", undefined, { class: "actions" });
      actions.append(element("a", "Details", { href: `/config/devices/device/${encodeURIComponent(device.id)}` }),
        this.button("Remove", () => { this.removing = device; this.render(); }));
      row.append(label, actions);
      main.append(row);
    }
    this.shadowRoot.append(main);
    main.inert = !!this.removing || !!this.flow.result;
    if (this.removing) this.renderRemoval();
    else if (this.flow.result) this.renderFlow();
    if (this.removing || this.flow.result) {
      const target = (focusId && this.shadowRoot.getElementById(focusId)) ||
        (focusLabel && [...this.shadowRoot.querySelectorAll(".dialog button")].find(b => b.textContent === focusLabel && !b.disabled)) ||
        this.shadowRoot.getElementById("dialog-title");
      target?.focus({ preventScroll: true });
    }
  }
  dialog(title) {
    const overlay = element("div", undefined, { class: "overlay" });
    const dialog = element("section", undefined, { class: "dialog", role: "dialog", "aria-modal": "true", "aria-labelledby": "dialog-title" });
    dialog.append(element("h2", title, { id: "dialog-title", tabindex: "-1" }));
    dialog.addEventListener("keydown", event => {
      if (event.key === "Tab") {
        const controls = [...dialog.querySelectorAll("button:not(:disabled),input:not(:disabled),select:not(:disabled),a[href]")];
        const first = controls[0], last = controls.at(-1), current = this.shadowRoot.activeElement;
        if (event.shiftKey && (current === first || current?.id === "dialog-title")) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && current === last) { event.preventDefault(); first?.focus(); }
      }
    });
    overlay.append(dialog);
    this.shadowRoot.append(overlay);
    return dialog;
  }
  renderRemoval() {
    const device = this.removing;
    const dialog = this.dialog(`Remove ${device.name}?`);
    dialog.append(element("p", "Remove its local association and HA entities. This does not factory-reset the physical device."));
    if (this.message) dialog.append(element("p", this.message, { role: "status" }));
    const footer = element("footer");
    footer.append(this.button("Back", () => { this.removing = null; this.render(); }), this.button("Remove device", () => this.removeDevice(device), true));
    dialog.append(footer);
  }
  saveInputs(form) {
    const data = {};
    const draft = {};
    for (const input of form.querySelectorAll("[name]")) {
      draft[input.name] = input.type === "number" && input.value ? Number(input.value) : input.value;
      if (!input.value && !input.required) continue;
      data[input.name] = draft[input.name];
    }
    this.flow.drafts[form.dataset.step] = draft;
    return data;
  }
  field(schema, labels) {
    const wrapper = element("div");
    const id = `field-${schema.name}`;
    wrapper.append(element("label", labels[schema.name] || schema.name, { for: id }));
    let input;
    const isArea = schema.selector?.area !== undefined;
    const choices = isArea ? this.inventory.areas.map(a => [a.area_id, a.name]) : schema.options;
    if (choices) {
      input = element("select");
      if (!schema.required || isArea) input.append(element("option", "No area", { value: "" }));
      for (const option of choices) {
        const [value, label] = Array.isArray(option) ? option : [option.value ?? option, option.label ?? option];
        input.append(element("option", label, { value }));
      }
    } else {
      const number = ["integer", "float"].includes(schema.type) || schema.name === "duration_seconds";
      input = element("input", undefined, { type: number ? "number" : "text" });
      if (schema.name === "duration_seconds") { input.min = "10"; input.max = "900"; input.step = "1"; }
    }
    input.id = id;
    input.name = schema.name;
    input.required = !!schema.required;
    input.disabled = this.flow.busy;
    const draft = this.flow.drafts[this.flow.result.step_id] || {};
    const value = draft[schema.name] ?? schema.default ?? schema.description?.suggested_value;
    if (value !== undefined && (input.tagName !== "SELECT" || [...input.options].some(o => o.value === String(value)))) input.value = value;
    wrapper.append(input);
    return wrapper;
  }
  renderFlow() {
    const flow = this.flow;
    const result = flow.result;
    const strings = this.inventory.strings;
    const step = strings.step?.[result.step_id] || {};
    const values = result.description_placeholders || {};
    const title = result.type === "create_entry" ? "Device setup saved" : result.type === "abort" ? "Pairing did not finish" : interpolate(step.title || "Add a RainPoint device", values);
    const dialog = this.dialog(flow.successReview ? "Pairing accepted" : title);
    dialog.append(element("div", "Category → Model → Radio → Review → Pair → Details", { class: "steps" }));
    if (flow.notice) dialog.append(element("p", flow.notice, { class: "notice", role: "status" }));
    if (flow.error) dialog.append(element("p", flow.error, { class: "notice error", role: "alert" }));
    if (flow.successReview) {
      dialog.append(element("p", "The device confirmed its local identity. Next returns to its name and area; it does not repeat pairing."));
    } else {
      if (result.step_id === "pairing_review") dialog.append(element("p", `Pair ${values.device_name} using ${values.node_name}. Start pairing arms the radio for ${values.duration_seconds} seconds. Back changes the radio settings without transmitting.`));
      else if (step.description) dialog.append(element("p", interpolate(step.description, values)));
      for (const [field, error] of Object.entries(result.errors || {})) dialog.append(element("p", strings.error?.[error] || error, { class: "fields-error", role: "alert" }));
      if (result.type === "abort") dialog.append(element("p", strings.abort?.[result.reason] || "The pairing window expired or the gateway rejected the request. Back keeps your selections for another attempt.", { class: "notice error", role: "alert" }));
      if (result.type === "show_progress") dialog.append(element("p", interpolate(strings.progress?.[result.progress_action] || "Waiting for the gateway…", values), { class: "progress", role: "status", "aria-live": "polite" }));
      if (result.type === "form") {
        const form = element("form", undefined, { "data-step": result.step_id });
        for (const schema of result.data_schema || []) form.append(this.field(schema, step.data || {}));
        form.onsubmit = event => { event.preventDefault(); if (form.reportValidity()) flow.submit(this.saveInputs(form)); };
        dialog.append(form);
      }
      if (result.type === "menu" && result.step_id !== "pairing_review") {
        const menu = element("div", undefined, { class: "menus" });
        for (const option of result.menu_options || []) menu.append(this.button(step.menu_options?.[option] || option, () => flow.submit({ next_step_id: option })));
        dialog.append(menu);
      }
    }
    const footer = element("footer");
    if (result.type === "create_entry") {
      footer.append(this.button("Back to devices", () => this.leave(), true));
    } else {
      footer.append(this.button("Back", () => this.leave(true)));
      if (result.type === "form" || flow.successReview) footer.append(this.button(flow.successReview ? "Next" : result.step_id === "device_details" ? "Save device" : "Next", () => {
        if (flow.successReview) flow.submit({});
        else dialog.querySelector("form").requestSubmit();
      }, true));
      if (result.step_id === "pairing_review") footer.append(this.button("Start pairing", () => flow.submit({ next_step_id: "start_pairing" }), true));
      if (flow.error || result.type === "show_progress") footer.append(this.button("Refresh status", () => flow.refresh()));
      footer.append(this.button(result.type === "show_progress" ? "Stop and close" : "Close", () => this.leave()));
    }
    dialog.append(footer);
  }
}
customElements.define("rainpoint-device-panel", RainPointDevicePanel);
