import { LitElement, html, css } from "lit";
import { wsClient } from "./ws-client.js";
import "./screens/main-menu.js";
import "./screens/test-selection.js";
import "./screens/test-runner-screen.js";
import "./screens/results-summary.js";
import "./screens/estop-modal.js";

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
    uiPicoConnected: { type: Boolean },
  };

  static styles = css`
    :host {
      display: block;
      box-sizing: border-box;
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

    .link-down {
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      box-sizing: border-box;
      height: var(--link-banner-height);
      line-height: 20px;
      background: var(--red);
      color: white;
      padding: 10px 16px;
      text-align: center;
      font-size: 17px;
      font-weight: 700;
      letter-spacing: 1px;
      z-index: 200;
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
    // Assume the link is up until the first message says otherwise: the
    // banner would otherwise flash on every page load. The websocket sends
    // the real value in its initial state_change.
    this.uiPicoConnected = true;
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

    if (data.ui_pico_connected !== undefined) {
      this.uiPicoConnected = data.ui_pico_connected;
    }

    if (data.type === "state_change") {
      if (data.state === "estop") {
        // Remember the underlying state so the previous screen stays visible
        // behind the transient ESTOP modal. Don't overwrite it on duplicate
        // estop messages — that would clobber the real underlying state.
        if (this.state !== "estop") {
          this._preEstopState = this.state;
        }
      } else {
        this._preEstopState = null;
      }
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
    } else if (data.type === "ui_pico_disconnected") {
      this.uiPicoConnected = false;
    } else if (data.type === "ui_pico_connected") {
      this.uiPicoConnected = true;
    } else if (data.type === "start_refused") {
      // The link dropped between rendering the button and the click. Mark it
      // down so the banner appears and the screen releases its Starting state.
      this.uiPicoConnected = false;
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
      // Render whichever screen was active before the e-stop, with the modal
      // overlaid on top. The modal auto-dismisses when the backend transitions
      // out of ESTOP (~2.5 s) — no user action required on the happy path.
      return html`
        ${this._renderForState(this._preEstopState || "idle")}
        <estop-modal
          .powerOffFailed=${this.powerOffFailed}
          @clear-estop=${this._onClearEstop}
        ></estop-modal>
      `;
    }
    return this._renderForState(this.state);
  }

  _renderForState(state) {
    if (state === "booting") {
      return html`
        <div class="loading">
          <div class="spinner"></div>
          <h1>Starting...</h1>
        </div>
      `;
    }

    if (state === "results_pass" || state === "results_fail" || state === "running") {
      return html`
        ${this._renderStatusBanners()}
        <test-runner-screen
          .progress=${this.progress}
          .outputLines=${this.outputLines}
          .currentTestStartIndex=${this._currentTestStartIndex}
          .selectedDut=${this.selectedDut}
          .result=${state.startsWith("results_") ? this.result : null}
          .finished=${state.startsWith("results_")}
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
          ${this._renderStatusBanners()}
          <test-selection
            .dut=${dut}
            .initialPath=${this._browsePath}
            .savedTargets=${this._selectedTargets}
            .linkUp=${this.uiPicoConnected}
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
      ${this._renderStatusBanners()}
      <main-menu
        .duts=${this.duts}
        .sandwichType=${this.sandwichType}
        .sandwichDetectionComplete=${this.sandwichDetectionComplete}
        @select-dut=${this._onSelectDut}
      ></main-menu>
    `;
  }

  updated() {
    this.classList.toggle("link-down", this.connected && !this.uiPicoConnected);
  }

  _renderStatusBanners() {
    if (!this.connected) {
      return html`<div class="disconnected">Disconnected</div>`;
    }
    if (this.uiPicoConnected) return null;
    return html`
      <div class="link-down" role="alert">
        UI Pico link down — E-Stop button is not active
      </div>
    `;
  }
}

customElements.define("app-shell", AppShell);
