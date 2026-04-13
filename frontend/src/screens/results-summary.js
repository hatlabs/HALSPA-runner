import { LitElement, html, css } from "lit";

class ResultsSummary extends LitElement {
  static properties = {
    result: { type: Object },
    progress: { type: Object },
  };

  static styles = css`
    :host {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      height: 100vh;
      padding: 32px;
      gap: 24px;
    }

    .indicator {
      font-size: 4rem;
      font-weight: 700;
      padding: 24px 48px;
      border-radius: 16px;
    }

    .indicator.pass {
      background: var(--green);
      color: white;
    }

    .indicator.fail {
      background: var(--red);
      color: white;
    }

    .counts {
      display: flex;
      gap: 24px;
      font-size: 1.3rem;
    }

    .count-pass {
      color: var(--green);
    }
    .count-fail {
      color: var(--red);
    }
    .count-skip {
      color: var(--yellow);
    }
    .count-time {
      color: var(--text-dim);
    }

    .done-btn {
      background: var(--bg-card);
      color: var(--text);
      font-size: 1.3rem;
      font-weight: 600;
      padding: 16px 48px;
      margin-top: 16px;
    }

    .done-btn:active {
      background: var(--accent);
    }
  `;

  constructor() {
    super();
    this.result = null;
    this.progress = null;
  }

  _dismiss() {
    this.dispatchEvent(new CustomEvent("dismiss"));
  }

  render() {
    const r = this.result || {};
    const p = this.progress || {};
    const passed =
      r.status === "passed" || (r.failed === 0 && r.passed > 0);

    return html`
      <div class="indicator ${passed ? "pass" : "fail"}">
        ${passed ? "PASS" : "FAIL"}
      </div>

      <div class="counts">
        <span class="count-pass">${p.passed || r.passed || 0} passed</span>
        <span class="count-fail">${p.failed || r.failed || 0} failed</span>
        <span class="count-skip">${p.skipped || r.skipped || 0} skipped</span>
        <span class="count-time">${p.elapsed || r.elapsed || 0}s</span>
      </div>

      <button class="done-btn" @click=${this._dismiss}>Done</button>
    `;
  }
}

customElements.define("results-summary", ResultsSummary);
