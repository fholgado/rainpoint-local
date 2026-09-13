// Navigation adapter for HA's existing options flow. Never builds RF requests.
const API = "config/config_entries/options/flow";
const TERMINAL = new Set(["abort", "create_entry"]);

export class WizardFlow {
  constructor(hass, changed = () => {}, storage = globalThis.sessionStorage) {
    this.hass = hass;
    this.changed = changed;
    this.storage = storage;
    this.busy = false;
    this.result = null;
    this.drafts = {};
    this.error = "";
    this.notice = "";
    this.successReview = false;
  }

  async run(action) {
    if (this.busy) return;
    this.busy = true;
    this.error = "";
    this.changed();
    try { await action(); }
    catch {
      this.error = "The request could not be confirmed. Check the gateway, then refresh status before trying again.";
    } finally {
      this.busy = false;
      this.save();
      this.changed();
    }
  }

  save() {
    // Persist only the flow identity and non-secret selections, never credentials.
    try {
      if (this.result && !TERMINAL.has(this.result.type)) {
        this.storage?.setItem("rainpoint-wizard", JSON.stringify({
          flow_id: this.result.flow_id, entry_id: this.entryId, drafts: this.drafts,
        }));
      } else this.storage?.removeItem("rainpoint-wizard");
    } catch { /* Private browsing may disable storage; the RF window is bounded. */ }
  }

  async restore() {
    let saved;
    try { saved = JSON.parse(this.storage?.getItem("rainpoint-wizard") || "null"); }
    catch { return; }
    if (!saved?.flow_id || !saved.entry_id) return;
    this.entryId = saved.entry_id;
    this.drafts = saved.drafts || {};
    this.result = { flow_id: saved.flow_id, type: "show_progress" };
    await this.refresh();
  }

  async accept(result) {
    this.result = result;
    // HA normally resolves progress_done itself; support it explicitly as well.
    for (let i = 0; this.result.type === "show_progress_done" && i < 3; i++) {
      this.result = await this.hass.callApi("GET", `${API}/${this.result.flow_id}`);
    }
  }

  async begin(entryId) {
    return this.run(async () => {
      this.entryId = entryId;
      this.drafts = {};
      this.notice = "";
      await this.startFlow();
    });
  }

  async startFlow() {
    await this.accept(await this.hass.callApi("POST", API, { handler: this.entryId }));
    if (!this.result.menu_options?.includes("add_device")) {
      this.notice = "Finish authenticating the gateway in Devices & services first.";
      await this.cancel();
      this.result = { type: "abort", reason: "gateway_requires_auth" };
      return;
    }
    await this.post({ next_step_id: "add_device" });
  }

  async post(data) {
    await this.accept(await this.hass.callApi("POST", `${API}/${this.result.flow_id}`, data));
  }

  async submit(data) {
    return this.run(async () => {
      if (this.successReview) { this.successReview = false; return; }
      const step = this.result.step_id;
      this.drafts[step] = { ...data };
      await this.post(data);
    });
  }

  async refresh() {
    return this.run(async () => {
      if (this.result && !TERMINAL.has(this.result.type)) {
        await this.accept(await this.hass.callApi("GET", `${API}/${this.result.flow_id}`));
      }
    });
  }

  async cancel() {
    if (this.result && !TERMINAL.has(this.result.type)) {
      const status = await this.hass.callWS({ type: "rainpoint_local/wizard_cancel",
        entry_id: this.entryId, flow_id: this.result.flow_id });
      if (!status.closed) throw new Error("flow not closed");
      if (status.stop_requested) {
        this.notice = "Cancellation sent. The radio may take a moment to disarm; its original listening window still expires automatically.";
      }
    }
    this.result = null;
  }

  async close() {
    return this.run(async () => {
      await this.cancel();
      this.successReview = false;
    });
  }

  async back() {
    return this.run(async () => {
      const step = this.result?.step_id;
      if (step === "device_details") {
        // RF acceptance cannot be undone. Review it without restarting pairing.
        this.successReview = !this.successReview;
        return;
      }
      if (step === "pairing_review") {
        await this.post({ next_step_id: "change_pairing_radio" });
        return;
      }
      const category = this.drafts.add_device?.next_step_id;
      const model = this.drafts[category]?.profile_id;
      const returnToRadio = step === "pairing_progress" || this.result?.type === "abort";
      const returnToModel = step === "pair_device";
      await this.cancel();
      if (["add_sensor", "add_valve"].includes(step) || returnToModel || returnToRadio) {
        await this.startFlow();
        if (category && (returnToModel || returnToRadio)) {
          await this.post({ next_step_id: category });
          if (model && returnToRadio) await this.post({ profile_id: model });
        }
      }
      // After saving a device, Back returns to the list; it never unpairs it.
    });
  }
}
