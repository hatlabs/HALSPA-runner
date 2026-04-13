import { LitElement, html, css } from "lit";

class TestRunnerScreen extends LitElement {
  static properties = {
    progress: { type: Object },
    outputLines: { type: Array },
    selectedDut: { type: String },
    autoScroll: { type: Boolean },
  };

  static styles = css`
    :host {
      display: flex;
      flex-direction: column;
      height: 100vh;
      padding: 16px 24px;
    }

    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
    }

    h1 {
      font-size: 1.4rem;
    }

    .stats {
      display: flex;
      gap: 16px;
      font-size: 1.1rem;
      font-weight: 600;
    }

    .stat-pass {
      color: var(--green);
    }
    .stat-fail {
      color: var(--red);
    }
    .stat-skip {
      color: var(--yellow);
    }
    .stat-time {
      color: var(--text-dim);
    }

    .current-test {
      color: var(--text-dim);
      font-size: 0.9rem;
      margin-bottom: 8px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .log-container {
      flex: 1;
      position: relative;
      overflow: hidden;
    }

    .log {
      height: 100%;
      overflow-y: auto;
      background: #0d1117;
      border-radius: 8px;
      padding: 12px;
      font-family: var(--font-mono);
      font-size: 14px;
      line-height: 1.4;
      color: #c9d1d9;
    }

    .log-line {
      white-space: pre-wrap;
      word-break: break-all;
    }

    .log-line.pass {
      color: var(--green);
    }
    .log-line.fail {
      color: var(--red);
    }

    .snap-btn {
      position: absolute;
      bottom: 12px;
      right: 12px;
      background: var(--accent);
      color: white;
      font-size: 0.9rem;
      padding: 8px 16px;
      opacity: 0.9;
    }
  `;

  constructor() {
    super();
    this.progress = {};
    this.outputLines = [];
    this.selectedDut = "";
    this.autoScroll = true;
  }

  updated(changed) {
    if (changed.has("outputLines") && this.autoScroll) {
      this._scrollToBottom();
    }
  }

  _scrollToBottom() {
    const log = this.shadowRoot?.querySelector(".log");
    if (log) {
      log.scrollTop = log.scrollHeight;
    }
  }

  _onScroll(e) {
    const log = e.target;
    const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    this.autoScroll = atBottom;
  }

  _snapToBottom() {
    this.autoScroll = true;
    this._scrollToBottom();
  }

  _lineClass(line) {
    if (line.includes(" PASSED")) return "pass";
    if (line.includes(" FAILED") || line.includes(" ERROR")) return "fail";
    return "";
  }

  render() {
    const p = this.progress || {};

    return html`
      <header>
        <h1>Running: ${this.selectedDut}</h1>
        <div class="stats">
          <span class="stat-pass">${p.passed || 0} passed</span>
          <span class="stat-fail">${p.failed || 0} failed</span>
          <span class="stat-skip">${p.skipped || 0} skipped</span>
          <span class="stat-time">${p.elapsed || 0}s</span>
        </div>
      </header>

      <div class="current-test">${p.current_test || ""}</div>

      <div class="log-container">
        <div class="log" @scroll=${this._onScroll}>
          ${this.outputLines.map(
            (line) =>
              html`<div class="log-line ${this._lineClass(line)}">${line}</div>`
          )}
        </div>
        ${!this.autoScroll
          ? html`<button class="snap-btn" @click=${this._snapToBottom}>
              Snap to bottom
            </button>`
          : null}
      </div>
    `;
  }
}

customElements.define("test-runner-screen", TestRunnerScreen);
