import { LitElement, html, css } from "lit";
import { TouchFeedback } from "../touch-feedback.js";

class MainMenu extends LitElement {
  static properties = {
    duts: { type: Array },
    sandwichType: { type: String },
    showShutdown: { type: Boolean },
    shuttingDown: { type: Boolean },
  };

  static styles = css`
    :host {
      display: flex;
      flex-direction: column;
      height: 100vh;
      padding: 24px;
      box-sizing: border-box;
    }

    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 24px;
    }

    h1 {
      font-size: 1.8rem;
      font-weight: 600;
    }

    .power-btn {
      background: var(--bg-card);
      color: var(--text-dim);
      font-size: 1.4rem;
      width: 48px;
      height: 48px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 0;
    }

    .dut-list {
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 12px;
      overflow-y: auto;
    }

    .dut-btn {
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: var(--bg-card);
      color: var(--text);
      font-size: 1.3rem;
      font-weight: 600;
      padding: 20px 24px;
      min-height: 80px;
      transition: background 0.15s;
    }

    .dut-btn.pressed {
      background: var(--accent);
    }

    .badge {
      background: var(--green);
      color: white;
      font-size: 0.8rem;
      padding: 4px 10px;
      border-radius: 12px;
      font-weight: 500;
    }

    .empty {
      flex: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--text-dim);
      font-size: 1.2rem;
    }

    .shutdown-overlay {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.7);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 50;
    }

    .shutdown-dialog {
      background: var(--bg-surface);
      padding: 32px;
      border-radius: 16px;
      text-align: center;
      max-width: 400px;
    }

    .shutdown-dialog h2 {
      margin-bottom: 16px;
    }

    .shutdown-dialog .actions {
      display: flex;
      gap: 12px;
      justify-content: center;
      margin-top: 24px;
    }

    .shutdown-dialog .cancel-btn {
      background: var(--bg-card);
      color: var(--text);
    }

    .shutdown-dialog .confirm-btn {
      background: var(--red);
      color: white;
    }

    button {
      transition: opacity 0.1s, transform 0.1s, background 0.15s;
    }

    button.pressed {
      opacity: 0.7;
      transform: scale(0.97);
    }

    button[disabled] {
      opacity: 0.5;
      pointer-events: none;
    }
  `;

  constructor() {
    super();
    this.duts = [];
    this.sandwichType = null;
    this.showShutdown = false;
    this.shuttingDown = false;
  }

  _selectDut(name) {
    this.dispatchEvent(
      new CustomEvent("select-dut", { detail: { dut: name } })
    );
  }

  async _shutdown() {
    this.shuttingDown = true;
    try {
      await fetch("/api/shutdown", { method: "POST" });
    } catch {
      this.shuttingDown = false;
    }
  }

  render() {
    return html`
      <header>
        <h1>HALSPA Test Runner</h1>
        <button
          class="power-btn"
          @pointerdown=${TouchFeedback.onPress}
          @pointerup=${TouchFeedback.onRelease}
          @pointerleave=${TouchFeedback.onRelease}
          @click=${() => (this.showShutdown = true)}
        >&#x23FB;</button>
      </header>

      ${this.duts.length === 0
        ? html`<div class="empty">No test suites found</div>`
        : html`
            <div class="dut-list">
              ${this.duts.map(
                (dut) => html`
                  <button
                    class="dut-btn"
                    ?disabled=${this.sandwichType && this.sandwichType !== dut.name}
                    @pointerdown=${TouchFeedback.onPress}
                    @pointerup=${TouchFeedback.onRelease}
                    @pointerleave=${TouchFeedback.onRelease}
                    @click=${() => this._selectDut(dut.name)}
                  >
                    <span>${dut.name}</span>
                    ${this.sandwichType === dut.name
                      ? html`<span class="badge">Detected</span>`
                      : null}
                  </button>
                `
              )}
            </div>
          `}

      ${this.showShutdown
        ? html`
            <div class="shutdown-overlay">
              <div class="shutdown-dialog">
                <h2>Shut down?</h2>
                <p>The system will power off.</p>
                <div class="actions">
                  <button
                    class="cancel-btn"
                    ?disabled=${this.shuttingDown}
                    @pointerdown=${TouchFeedback.onPress}
                    @pointerup=${TouchFeedback.onRelease}
                    @pointerleave=${TouchFeedback.onRelease}
                    @click=${() => (this.showShutdown = false)}
                  >
                    Cancel
                  </button>
                  <button
                    class="confirm-btn"
                    ?disabled=${this.shuttingDown}
                    @pointerdown=${TouchFeedback.onPress}
                    @pointerup=${TouchFeedback.onRelease}
                    @pointerleave=${TouchFeedback.onRelease}
                    @click=${this._shutdown}
                  >
                    ${this.shuttingDown ? "Shutting down…" : "Shut Down"}
                  </button>
                </div>
              </div>
            </div>
          `
        : null}
    `;
  }
}

customElements.define("main-menu", MainMenu);
