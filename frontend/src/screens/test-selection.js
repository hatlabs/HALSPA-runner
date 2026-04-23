import { LitElement, html, css } from "lit";
import { TouchFeedback } from "../touch-feedback.js";

class TestSelection extends LitElement {
  static properties = {
    dut: { type: Object },
    initialPath: { type: String },
    currentPath: { type: String },
    entries: { type: Array },
    breadcrumbs: { type: Array },
    loading: { type: Boolean },
    error: { type: String },
    runAll: { type: Boolean },
    selected: { type: Object },
    starting: { type: Boolean },
    savedTargets: { type: Array },
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
      align-items: center;
      gap: 12px;
      margin-bottom: 16px;
      min-height: 48px;
    }

    .back-btn {
      background: var(--bg-card);
      color: var(--text);
      font-size: 1.2rem;
      padding: 8px 16px;
      flex-shrink: 0;
    }

    .breadcrumbs {
      display: flex;
      align-items: center;
      gap: 4px;
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
      flex: 1;
      min-width: 0;
    }

    .breadcrumb {
      background: none;
      border: none;
      color: var(--accent);
      font-size: 1.1rem;
      padding: 8px 4px;
      min-height: 48px;
      white-space: nowrap;
      cursor: pointer;
      display: flex;
      align-items: center;
    }

    .breadcrumb.current {
      color: var(--text);
      font-weight: 600;
      cursor: default;
    }

    .breadcrumb-sep {
      color: var(--text-dim);
      font-size: 1rem;
      flex-shrink: 0;
    }

    .entries {
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 8px;
      overflow-y: auto;
    }

    .run-all-btn {
      display: flex;
      align-items: center;
      background: var(--bg-card);
      color: var(--text);
      font-size: 1.1rem;
      font-weight: 600;
      padding: 16px 20px;
      text-align: left;
      transition: background 0.15s;
      border-bottom: 2px solid var(--bg);
    }

    .run-all-btn.selected {
      background: var(--accent);
      color: white;
    }

    .entry-row {
      display: flex;
      align-items: stretch;
      background: var(--bg-card);
      border-radius: 8px;
      min-height: 56px;
      overflow: hidden;
    }

    .entry-row.selected {
      background: color-mix(in srgb, var(--accent) 25%, var(--bg-card));
    }

    .entry-checkbox {
      width: 72px;
      min-height: 56px;
      display: flex;
      align-items: center;
      justify-content: center;
      border: none;
      background: none;
      flex-shrink: 0;
      cursor: pointer;
      border-right: 1px solid var(--bg);
    }

    .check-box {
      width: 28px;
      height: 28px;
      border: 2px solid var(--text-dim);
      border-radius: 4px;
      display: flex;
      align-items: center;
      justify-content: center;
    }

    .entry-checkbox.checked .check-box {
      background: var(--accent);
      border-color: var(--accent);
    }

    .check-mark {
      display: none;
      width: 10px;
      height: 16px;
      border-right: 3px solid white;
      border-bottom: 3px solid white;
      transform: rotate(45deg) translate(-1px, -2px);
    }

    .entry-checkbox.checked .check-mark {
      display: block;
    }

    .entry-label {
      flex: 1;
      padding: 12px 16px;
      font-size: 1.1rem;
      min-height: 48px;
      display: flex;
      align-items: center;
      gap: 12px;
      border: none;
      background: none;
      color: var(--text);
      text-align: left;
      cursor: pointer;
    }

    .entry-label.leaf {
      cursor: default;
    }

    .type-icon {
      font-size: 0.85rem;
      padding: 2px 6px;
      border-radius: 4px;
      background: var(--bg);
      color: var(--text-dim);
      flex-shrink: 0;
    }

    .noauto-badge {
      font-size: 0.75rem;
      padding: 2px 8px;
      border-radius: 12px;
      background: color-mix(in srgb, var(--yellow) 20%, var(--bg-card));
      color: var(--yellow);
      flex-shrink: 0;
    }

    .drill-chevron {
      color: var(--text-dim);
      margin-left: auto;
      font-size: 1.2rem;
      flex-shrink: 0;
    }

    .empty-state {
      flex: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--text-dim);
      font-size: 1.2rem;
    }

    .spinner-container {
      flex: 1;
      display: flex;
      align-items: center;
      justify-content: center;
    }

    .spinner {
      width: 36px;
      height: 36px;
      border: 3px solid var(--bg-card);
      border-top-color: var(--accent);
      border-radius: 50%;
      animation: spin 1s linear infinite;
    }

    @keyframes spin {
      to { transform: rotate(360deg); }
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

    .start-btn.pressed {
      opacity: 0.8;
    }

    .start-btn[disabled] {
      background: var(--text-dim);
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
    this.dut = null;
    this.initialPath = "";
    this.currentPath = "";
    this.entries = [];
    this.breadcrumbs = [];
    this.loading = false;
    this.error = null;
    this.runAll = true;
    this.selected = new Set();
    this.starting = false;
    this.savedTargets = null;
    this._fetchGen = 0;
  }

  willUpdate(changed) {
    if (changed.has("dut") && this.dut) {
      this.currentPath = this.initialPath || "";
      this.starting = false;
      this._fetchEntries();
    }
    if (changed.has("currentPath") && !changed.has("dut")) {
      this._fetchEntries();
      this.dispatchEvent(new CustomEvent("browse", { detail: { path: this.currentPath } }));
    }
  }

  async _fetchEntries() {
    if (!this.dut) return;

    const gen = ++this._fetchGen;

    this.loading = true;
    this.error = null;
    this.entries = [];
    this.runAll = true;
    this.selected = new Set();

    try {
      const url = `/api/duts/${encodeURIComponent(this.dut.name)}/browse?path=${encodeURIComponent(this.currentPath)}`;
      const resp = await fetch(url);
      if (gen !== this._fetchGen) return;
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        this.error = data.error || `Error ${resp.status}`;
        return;
      }
      const data = await resp.json();
      this.entries = data.entries || [];
      this.breadcrumbs = data.breadcrumbs || [];
    } catch (e) {
      if (gen !== this._fetchGen) return;
      this.error = "Failed to fetch";
    } finally {
      if (gen === this._fetchGen) {
        this.loading = false;
      }
    }

    // Restore selection from savedTargets (one-shot after returning from test run)
    if (this.savedTargets && this.savedTargets.length > 0) {
      const entryPaths = new Set(this.entries.map((e) => e.path));
      const matching = this.savedTargets.filter((t) => entryPaths.has(t));
      if (matching.length > 0) {
        this.runAll = false;
        this.selected = new Set(matching);
      }
      this.dispatchEvent(new CustomEvent("clear-saved-targets"));
    }

    this._syncTargets();
  }

  _toggleRunAll() {
    if (this.runAll) return;
    this.runAll = true;
    this.selected = new Set();
    this._syncTargets();
  }

  _toggleEntry(path) {
    if (this.runAll) {
      this.runAll = false;
      this.selected = new Set([path]);
    } else if (this.selected.has(path)) {
      const next = new Set(this.selected);
      next.delete(path);
      this.selected = next;
      if (this.selected.size === 0) {
        this.runAll = true;
      }
    } else {
      this.selected = new Set([...this.selected, path]);
    }
    this._syncTargets();
  }

  _drillInto(entry) {
    if (entry.type === "function") return;
    this.currentPath = entry.path;
  }

  _navigateToBreadcrumb(crumb) {
    this.currentPath = crumb.path;
  }

  _back() {
    if (!this.currentPath) {
      this.dispatchEvent(new CustomEvent("back"));
    } else {
      const parts = this.currentPath.split("/");
      parts.pop();
      const parent = parts.join("/");
      // "tests" is the root level, represented as "" in the browse API
      this.currentPath = parent === "tests" ? "" : parent;
    }
  }

  _currentTargets() {
    if (!this.runAll) return [...this.selected];
    return this.currentPath ? [this.currentPath] : null;
  }

  _syncTargets() {
    this.dispatchEvent(
      new CustomEvent("select-targets", { detail: { targets: this._currentTargets() } })
    );
  }

  _start() {
    if (this.starting) return;
    this.starting = true;

    this.dispatchEvent(
      new CustomEvent("start-tests", {
        detail: { dut: this.dut.name, targets: this._currentTargets() },
      })
    );
  }

  _typeIcon(type) {
    if (type === "directory") return "DIR";
    if (type === "file") return "PY";
    return "fn";
  }

  render() {
    if (!this.dut) return null;

    return html`
      <header>
        <button
          class="back-btn"
          @pointerdown=${TouchFeedback.onPress}
          @pointerup=${TouchFeedback.onRelease}
          @pointerleave=${TouchFeedback.onRelease}
          @click=${this._back}
        >&larr;</button>
        <div class="breadcrumbs">
          <button
            class="breadcrumb ${this.breadcrumbs.length === 0 ? "current" : ""}"
            @click=${() => { this.currentPath = ""; }}
          >${this.dut.name}</button>
          ${this.breadcrumbs.map(
            (crumb, i) => html`
              <span class="breadcrumb-sep">&rsaquo;</span>
              <button
                class="breadcrumb ${i === this.breadcrumbs.length - 1 ? "current" : ""}"
                @click=${() => this._navigateToBreadcrumb(crumb)}
              >${crumb.name}</button>
            `
          )}
        </div>
      </header>

      ${this.loading
        ? html`<div class="spinner-container"><div class="spinner"></div></div>`
        : this.error
          ? html`<div class="empty-state">${this.error}</div>`
          : this.entries.length === 0
            ? html`<div class="empty-state">No tests found</div>`
            : this._renderEntries()
      }

      <footer>
        <button
          class="start-btn"
          ?disabled=${this.starting || this.loading}
          @pointerdown=${TouchFeedback.onPress}
          @pointerup=${TouchFeedback.onRelease}
          @pointerleave=${TouchFeedback.onRelease}
          @click=${this._start}
        >${this.starting ? "Starting…" : "Start Tests"}</button>
      </footer>
    `;
  }

  _renderEntries() {
    return html`
      <div class="entries">
        <button
          class="run-all-btn ${this.runAll ? "selected" : ""}"
          @pointerdown=${TouchFeedback.onPress}
          @pointerup=${TouchFeedback.onRelease}
          @pointerleave=${TouchFeedback.onRelease}
          @click=${this._toggleRunAll}
        >Run All</button>
        ${this.entries.map((entry) => this._renderEntry(entry))}
      </div>
    `;
  }

  _renderEntry(entry) {
    const isSelected = !this.runAll && this.selected.has(entry.path);
    const isLeaf = entry.type === "function";

    return html`
      <div class="entry-row ${isSelected ? "selected" : ""}">
        <button
          class="entry-checkbox ${isSelected ? "checked" : ""}"
          @pointerdown=${TouchFeedback.onPress}
          @pointerup=${TouchFeedback.onRelease}
          @pointerleave=${TouchFeedback.onRelease}
          @click=${() => this._toggleEntry(entry.path)}
        ><div class="check-box"><div class="check-mark"></div></div></button>
        <button
          class="entry-label ${isLeaf ? "leaf" : ""}"
          @pointerdown=${TouchFeedback.onPress}
          @pointerup=${TouchFeedback.onRelease}
          @pointerleave=${TouchFeedback.onRelease}
          @click=${() => isLeaf ? this._toggleEntry(entry.path) : this._drillInto(entry)}
        >
          <span class="type-icon">${this._typeIcon(entry.type)}</span>
          ${entry.name}
          ${entry.markers?.includes("noauto") ? html`<span class="noauto-badge">noauto</span>` : null}
          ${!isLeaf ? html`<span class="drill-chevron">&rsaquo;</span>` : null}
        </button>
      </div>
    `;
  }
}

customElements.define("test-selection", TestSelection);
