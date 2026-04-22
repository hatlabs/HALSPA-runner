import { LitElement, html, css } from "lit";
import { wsClient } from "./ws-client.js";
import "./screens/main-menu.js";
import "./screens/test-selection.js";
import "./screens/test-runner-screen.js";
import "./screens/results-summary.js";
import "./screens/estop-screen.js";

class AppShell extends LitElement {
  static properties = {
    state: { type: String },
    connected: { type: Boolean },
    selectedDut: { type: String },
    sandwichType: { type: String },
    sandwichDetectionComplete: { type: Boolean },
    duts: { type: Array },
    progress: { type: Object },
    outputLines: { type: Array },
    result: { type: Object },
    powerOffFailed: { type: Boolean },
  };

  static styles = css`
    :host {
      display: block;
      width: 100vw;
      height: 100vh;
      background: var(--bg);
    }

    .loading {
      display: flex;
      align-items: center;
      justify-content: center;
      height: 100%;
      flex-direction: column;
      gap: 16px;
    }

    .loading h1 {
      font-size: 2rem;
      color: var(--text-dim);
    }

    .loading .spinner {
      width: 48px;
      height: 48px;
      border: 4px solid var(--bg-card);
      border-top-color: var(--accent);
      border-radius: 50%;
      animation: spin 1s linear infinite;
    }

    .disconnected {
      position: fixed;
      top: 8px;
      right: 8px;
      background: var(--red);
      color: white;
      padding: 4px 12px;
      border-radius: 4px;
      font-size: 14px;
      z-index: 100;
    }

    @keyframes spin {
      to {
        transform: rotate(360deg);
      }
    }
  `;

  constructor() {
    super();
    this.state = "booting";
    this.connected = false;
    this.selectedDut = null;
    this.sandwichType = null;
    this.duts = [];
    this.progress = { passed: 0, failed: 0, skipped: 0, errors: 0, total: 0, current_test: "", elapsed: 0 };
    this.outputLines = [];
    this._currentTestStartIndex = 0;
    this.result = null;
    this.powerOffFailed = false;
    this._hasAutoSelected = false;
    this._dutsLoaded = false;
    this._browsePath = "";
    this._selectedTargets = null;

    this._boundOnMessage = this._onMessage.bind(this);
    this._boundOnConnected = () => {
      this.connected = true;
      this._fetchDuts();
    };
    this._boundOnDisconnected = () => { this.connected = false; };
  }

  connectedCallback() {
    super.connectedCallback();
    window.addEventListener("ws-message", this._boundOnMessage);
    window.addEventListener("ws-connected", this._boundOnConnected);
    window.addEventListener("ws-disconnected", this._boundOnDisconnected);
    wsClient.connect();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener("ws-message", this._boundOnMessage);
    window.removeEventListener("ws-connected", this._boundOnConnected);
    window.removeEventListener("ws-disconnected", this._boundOnDisconnected);
  }

  async _fetchDuts() {
    try {
      const resp = await fetch("/api/duts");
      this.duts = await resp.json();
    } catch (err) {
      console.error("Failed to fetch DUTs:", err);
      this.duts = [];
    }
    this._dutsLoaded = true;
    this._tryAutoSelectSandwich();
  }

  _tryAutoSelectSandwich() {
    if (this._hasAutoSelected || !this.sandwichType || this.selectedDut) return;
    if (this.state !== "idle") return;
    const match = this.duts.find((d) => d.name === this.sandwichType);
    if (match) {
      this._hasAutoSelected = true;
      this._onSelectDut({ detail: { dut: match.name } });
    }
  }

  _onMessage(e) {
    const data = e.detail;

    if (data.type === "state_change") {
      this.state = data.state;
      if (data.selected_dut !== undefined) {
        this.selectedDut = data.selected_dut;
      }
      if (data.sandwich_detection_complete !== undefined) {
        this.sandwichDetectionComplete = data.sandwich_detection_complete;
      }
      if (data.sandwich_type !== undefined) {
        this.sandwichType = data.sandwich_type;
        // If backend already has a matching DUT selected (e.g., after browser
        // reload), mark auto-select as done so back arrow works correctly.
        if (this.selectedDut && this.selectedDut === this.sandwichType) {
          this._hasAutoSelected = true;
        }
        this._tryAutoSelectSandwich();
      }
      if (data.state === "estop") {
        this.powerOffFailed = data.power_off_failed || false;
      }
      if (data.state === "idle") {
        this.selectedDut = null;
        this._browsePath = "";
        this._selectedTargets = null;
        this.outputLines = [];
        this.result = null;
        this.progress = { passed: 0, failed: 0, skipped: 0, errors: 0, total: 0, current_test: "", elapsed: 0 };
        this._dutsLoaded = false;
        this._fetchDuts();
      } else if (data.state === "dut_selected") {
        this.outputLines = [];
        this.result = null;
        this.progress = { passed: 0, failed: 0, skipped: 0, errors: 0, total: 0, current_test: "", elapsed: 0 };
        this._fetchDuts();
      }
    } else if (data.type === "test_output") {
      this.outputLines = [...this.outputLines, data.line];
    } else if (data.type === "test_start") {
      this._currentTestStartIndex = this.outputLines.length;
      this.requestUpdate();
    } else if (data.type === "test_progress") {
      this.progress = data;
    } else if (data.type === "test_complete") {
      this.result = data;
    }
  }

  _onSelectDut(e) {
    this.selectedDut = e.detail.dut;
    wsClient.send({ type: "select_dut", dut: e.detail.dut });
  }

  _onStartTests(e) {
    const { dut, targets } = e.detail;
    this._selectedTargets = targets;
    this.outputLines = [];
    this._currentTestStartIndex = 0;
    this.progress = { passed: 0, failed: 0, skipped: 0, errors: 0, total: 0, current_test: "", elapsed: 0 };
    this.result = null;
    wsClient.send({ type: "start", dut, targets });
  }

  _onSelectTargets(e) {
    wsClient.send({ type: "select", targets: e.detail.targets });
  }

  _onBrowse(e) {
    this._browsePath = e.detail.path;
  }

  _onClearSavedTargets() {
    this._selectedTargets = null;
  }

  _onStop() {
    wsClient.send({ type: "stop" });
  }

  _onBack() {
    this.selectedDut = null;
    wsClient.send({ type: "deselect" });
  }

  _onDismiss() {
    wsClient.send({ type: "dismiss" });
  }

  _onClearEstop() {
    wsClient.send({ type: "clear_estop" });
  }

  render() {
    if (this.state === "estop") {
      return html`
        ${this._renderDisconnected()}
        <estop-screen
          .powerOffFailed=${this.powerOffFailed}
          @clear-estop=${this._onClearEstop}
        ></estop-screen>
      `;
    }

    if (this.state === "booting") {
      return html`
        <div class="loading">
          <div class="spinner"></div>
          <h1>Starting...</h1>
        </div>
      `;
    }

    if (this.state === "results_pass" || this.state === "results_fail" || this.state === "running") {
      return html`
        ${this._renderDisconnected()}
        <test-runner-screen
          .progress=${this.progress}
          .outputLines=${this.outputLines}
          .currentTestStartIndex=${this._currentTestStartIndex}
          .selectedDut=${this.selectedDut}
          .result=${this.state.startsWith("results_") ? this.result : null}
          .finished=${this.state.startsWith("results_")}
          @stop=${this._onStop}
          @dismiss=${this._onDismiss}
        ></test-runner-screen>
      `;
    }

    if (this.selectedDut) {
      const dut = this.duts.find((d) => d.name === this.selectedDut);
      if (!dut && this._dutsLoaded) {
        // DUT no longer available (removed between runs) — fall back to menu
        this.selectedDut = null;
      } else if (dut) {
        return html`
          ${this._renderDisconnected()}
          <test-selection
            .dut=${dut}
            .initialPath=${this._browsePath}
            .savedTargets=${this._selectedTargets}
            @start-tests=${this._onStartTests}
            @select-targets=${this._onSelectTargets}
            @browse=${this._onBrowse}
            @clear-saved-targets=${this._onClearSavedTargets}
            @back=${this._onBack}
          ></test-selection>
        `;
      }
    }

    return html`
      ${this._renderDisconnected()}
      <main-menu
        .duts=${this.duts}
        .sandwichType=${this.sandwichType}
        .sandwichDetectionComplete=${this.sandwichDetectionComplete}
        @select-dut=${this._onSelectDut}
      ></main-menu>
    `;
  }

  _renderDisconnected() {
    if (this.connected) return null;
    return html`<div class="disconnected">Disconnected</div>`;
  }
}

customElements.define("app-shell", AppShell);
