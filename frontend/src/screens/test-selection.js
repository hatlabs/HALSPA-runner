import { LitElement, html, css } from "lit";

class TestSelection extends LitElement {
  static properties = {
    dut: { type: Object },
    runAll: { type: Boolean },
    selected: { type: Array },
  };

  static styles = css`
    :host {
      display: flex;
      flex-direction: column;
      height: 100vh;
      padding: 24px;
    }

    header {
      display: flex;
      align-items: center;
      gap: 16px;
      margin-bottom: 24px;
    }

    .back-btn {
      background: var(--bg-card);
      color: var(--text);
      font-size: 1.2rem;
      padding: 8px 16px;
    }

    h1 {
      font-size: 1.6rem;
    }

    .categories {
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 8px;
      overflow-y: auto;
    }

    .cat-btn {
      display: flex;
      align-items: center;
      background: var(--bg-card);
      color: var(--text);
      font-size: 1.1rem;
      padding: 16px 20px;
      text-align: left;
      transition: background 0.15s;
    }

    .cat-btn.selected {
      background: var(--accent);
      color: white;
    }

    .cat-btn.run-all {
      font-weight: 600;
      border-bottom: 2px solid var(--bg);
    }

    footer {
      padding-top: 16px;
    }

    .start-btn {
      width: 100%;
      background: var(--green);
      color: white;
      font-size: 1.3rem;
      font-weight: 600;
      padding: 16px;
    }

    .start-btn:active {
      opacity: 0.8;
    }
  `;

  constructor() {
    super();
    this.dut = null;
    this.runAll = true;
    this.selected = [];
  }

  _toggleRunAll() {
    this.runAll = !this.runAll;
    if (this.runAll) {
      this.selected = [];
    }
  }

  _toggleCategory(name) {
    if (this.runAll) {
      this.runAll = false;
      this.selected = [name];
    } else if (this.selected.includes(name)) {
      this.selected = this.selected.filter((s) => s !== name);
      if (this.selected.length === 0) {
        this.runAll = true;
      }
    } else {
      this.selected = [...this.selected, name];
    }
  }

  _start() {
    const categories = this.runAll
      ? null
      : this.selected.length > 0
        ? this.selected
        : null;

    this.dispatchEvent(
      new CustomEvent("start-tests", {
        detail: { dut: this.dut.name, categories },
      })
    );
  }

  _back() {
    this.dispatchEvent(new CustomEvent("back"));
  }

  render() {
    if (!this.dut) return null;

    return html`
      <header>
        <button class="back-btn" @click=${this._back}>&larr; Back</button>
        <h1>${this.dut.name}</h1>
      </header>

      <div class="categories">
        <button
          class="cat-btn run-all ${this.runAll ? "selected" : ""}"
          @click=${this._toggleRunAll}
        >
          Run All
        </button>
        ${(this.dut.categories || []).map(
          (cat) => html`
            <button
              class="cat-btn ${!this.runAll && this.selected.includes(cat.name) ? "selected" : ""}"
              @click=${() => this._toggleCategory(cat.name)}
            >
              ${cat.name}
            </button>
          `
        )}
      </div>

      <footer>
        <button class="start-btn" @click=${this._start}>Start Tests</button>
      </footer>
    `;
  }
}

customElements.define("test-selection", TestSelection);
