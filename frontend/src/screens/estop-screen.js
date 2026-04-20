import { LitElement, html, css } from "lit";
import { TouchFeedback } from "../touch-feedback.js";

class EstopScreen extends LitElement {
  static properties = {
    powerOffFailed: { type: Boolean },
    clearing: { type: Boolean },
  };

  static styles = css`
    :host {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      height: 100vh;
      background: var(--red);
      gap: 24px;
    }

    h1 {
      font-size: 3rem;
      font-weight: 800;
      color: white;
      text-transform: uppercase;
      letter-spacing: 4px;
    }

    .warning {
      background: rgba(0, 0, 0, 0.3);
      color: white;
      padding: 12px 24px;
      border-radius: 8px;
      font-size: 1.1rem;
      max-width: 500px;
      text-align: center;
    }

    .clear-btn {
      background: white;
      color: var(--red);
      font-size: 1.3rem;
      font-weight: 700;
      padding: 16px 48px;
      margin-top: 16px;
    }

    .clear-btn.pressed {
      opacity: 0.8;
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
    this.powerOffFailed = false;
    this.clearing = false;
  }

  _clear() {
    if (this.clearing) return;
    this.clearing = true;
    this.dispatchEvent(new CustomEvent("clear-estop"));
  }

  render() {
    return html`
      <h1>E-Stop Activated</h1>

      ${this.powerOffFailed
        ? html`<div class="warning">
            Warning: I2C power-off failed. Manually verify power is off before
            proceeding.
          </div>`
        : null}

      <button
        class="clear-btn"
        ?disabled=${this.clearing}
        @pointerdown=${TouchFeedback.onPress}
        @pointerup=${TouchFeedback.onRelease}
        @pointerleave=${TouchFeedback.onRelease}
        @click=${this._clear}
      >
        ${this.clearing ? "Clearing…" : "Clear & Return to Menu"}
      </button>
    `;
  }
}

customElements.define("estop-screen", EstopScreen);
