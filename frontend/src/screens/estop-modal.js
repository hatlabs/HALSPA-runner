import { LitElement, html, css } from "lit";
import { TouchFeedback } from "../touch-feedback.js";

class EstopModal extends LitElement {
  static properties = {
    powerOffFailed: { type: Boolean },
    clearing: { type: Boolean },
  };

  static styles = css`
    :host {
      position: fixed;
      inset: 0;
      z-index: 1000;
      display: flex;
      align-items: center;
      justify-content: center;
      background: rgba(0, 0, 0, 0.55);
    }

    .panel {
      background: var(--red);
      border-radius: 16px;
      padding: 48px 64px;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 20px;
      box-shadow: 0 16px 48px rgba(0, 0, 0, 0.4);
      min-width: 480px;
      max-width: 640px;
    }

    h1 {
      font-size: 2.6rem;
      font-weight: 800;
      color: white;
      text-transform: uppercase;
      letter-spacing: 4px;
      margin: 0;
    }

    .warning {
      background: rgba(0, 0, 0, 0.3);
      color: white;
      padding: 12px 20px;
      border-radius: 8px;
      font-size: 1.1rem;
      text-align: center;
    }

    .force-btn {
      background: white;
      color: var(--red);
      font-size: 1.1rem;
      font-weight: 700;
      padding: 12px 32px;
      border-radius: 8px;
      border: none;
      cursor: pointer;
      transition: opacity 0.1s, transform 0.1s;
    }

    .force-btn.pressed {
      opacity: 0.7;
      transform: scale(0.97);
    }

    .force-btn[disabled] {
      opacity: 0.5;
      pointer-events: none;
    }
  `;

  constructor() {
    super();
    this.powerOffFailed = false;
    this.clearing = false;
  }

  _forceClear() {
    if (this.clearing) return;
    this.clearing = true;
    this.dispatchEvent(new CustomEvent("clear-estop"));
  }

  render() {
    return html`
      <div class="panel" role="alertdialog" aria-label="E-stop activated">
        <h1>E-Stop Activated</h1>
        ${this.powerOffFailed
          ? html`
              <div class="warning">
                I2C power-off failed. Verify power is off manually before proceeding.
              </div>
              <button
                class="force-btn"
                ?disabled=${this.clearing}
                @pointerdown=${TouchFeedback.onPress}
                @pointerup=${TouchFeedback.onRelease}
                @pointerleave=${TouchFeedback.onRelease}
                @click=${this._forceClear}
              >
                ${this.clearing ? "Clearing…" : "Force Clear"}
              </button>
            `
          : null}
      </div>
    `;
  }
}

customElements.define("estop-modal", EstopModal);
