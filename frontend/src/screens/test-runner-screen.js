import { LitElement, html, css } from "lit";
import { TouchFeedback } from "../touch-feedback.js";

class TestRunnerScreen extends LitElement {
  static properties = {
    progress: { type: Object },
    outputLines: { type: Array },
    currentTestStartIndex: { type: Number },
    selectedDut: { type: String },
    result: { type: Object },
    finished: { type: Boolean },
    autoScroll: { type: Boolean },
    stopping: { type: Boolean },
  };

  static styles = css`
    :host {
      display: flex;
      flex-direction: column;
      height: 100vh;
      padding: 16px 24px;
      box-sizing: border-box;
    }

    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
    }

    .header-left {
      display: flex;
      align-items: center;
      gap: 16px;
    }

    h1 {
      font-size: 1.4rem;
    }

    .progress-count {
      font-size: 1.2rem;
      font-weight: 600;
      color: var(--accent);
    }

    .stop-btn {
      background: var(--red);
      color: white;
      font-size: 1.1rem;
      font-weight: 600;
      padding: 10px 24px;
      min-height: 44px;
    }

    .stop-btn.pressed {
      opacity: 0.8;
    }

    .result-badge {
      font-size: 1.1rem;
      font-weight: 700;
      padding: 10px 24px;
      border-radius: 8px;
      color: white;
    }

    .result-badge.pass {
      background: var(--green);
    }

    .result-badge.fail {
      background: var(--red);
    }

    .done-btn {
      background: var(--bg-card);
      color: var(--text);
      font-size: 1.1rem;
      font-weight: 600;
      padding: 10px 24px;
      min-height: 44px;
    }

    .done-btn.pressed {
      background: var(--accent);
    }

    .header-right {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .stats {
      display: flex;
      gap: 16px;
      font-size: 1rem;
      font-weight: 600;
      margin-bottom: 4px;
    }

    .stat-pass {
      color: var(--green);
    }
    .stat-fail {
      color: var(--red);
    }
    .stat-fail--active {
      background: var(--red);
      color: var(--bg);
      padding: 0 6px;
      border-radius: 3px;
    }
    .stat-skip {
      color: var(--yellow);
    }
    .stat-time {
      color: var(--text-dim);
    }

    .current-test {
      color: var(--text-dim);
      font-size: 1.1rem;
      font-family: var(--font-mono);
      margin-bottom: 8px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .log-container {
      flex: 1;
      position: relative;
      overflow: hidden;
      min-height: 0;
    }

    .log {
      height: 100%;
      overflow-y: auto;
      background: #0d1117;
      border-radius: 8px;
      padding: 12px 56px 24px 12px;
      box-sizing: border-box;
      font-family: var(--font-mono);
      font-size: 14px;
      line-height: 1.4;
      color: #c9d1d9;
      scrollbar-width: none; /* Chromium 147 ignores ::-webkit-scrollbar; custom overlay below */
      -webkit-user-select: text;
      user-select: text;
    }

    .log-scroll-track {
      position: absolute;
      top: 0;
      right: 0;
      width: 48px;
      height: 100%;
      background: #1c2333;
      border-radius: 0 8px 8px 0;
    }

    .log-scroll-thumb {
      position: absolute;
      right: 4px;
      width: 40px;
      min-height: 48px;
      background: #6b7685;
      border-radius: 10px;
      touch-action: none;
      cursor: grab;
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
    this.progress = {};
    this.outputLines = [];
    this.currentTestStartIndex = 0;
    this.selectedDut = "";
    this.result = null;
    this.finished = false;
    this.autoScroll = true;
    this.stopping = false;
  }

  updated(changed) {
    if (changed.has("finished") && this.finished) {
      this.stopping = false;
    }
    if (changed.has("outputLines") && this.autoScroll) {
      this._scrollToBottom();
    }
  }

  _scrollToBottom() {
    const log = this._logEl();
    if (log) {
      log.scrollTop = log.scrollHeight;
      this._updateScrollThumb();
    }
  }

  _logEl() {
    return this._cachedLog ??= this.shadowRoot?.querySelector(".log");
  }
  _trackEl() {
    return this._cachedTrack ??= this.shadowRoot?.querySelector(".log-scroll-track");
  }
  _thumbEl() {
    return this._cachedThumb ??= this.shadowRoot?.querySelector(".log-scroll-thumb");
  }

  _onScroll(e) {
    const log = e.target;
    const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    this.autoScroll = atBottom;
    this._updateScrollThumb();
  }

  _updateScrollThumb() {
    const log = this._logEl();
    const thumb = this._thumbEl();
    const track = this._trackEl();
    if (!log || !thumb || !track) return;
    const ratio = log.clientHeight / log.scrollHeight;
    if (ratio >= 1) {
      track.style.display = "none";
      return;
    }
    track.style.display = "";
    const thumbHeight = Math.max(40, track.clientHeight * ratio);
    const scrollRange = log.scrollHeight - log.clientHeight;
    const trackRange = track.clientHeight - thumbHeight;
    if (trackRange <= 0) return;
    const thumbTop = scrollRange > 0 ? (log.scrollTop / scrollRange) * trackRange : 0;
    thumb.style.height = thumbHeight + "px";
    thumb.style.top = thumbTop + "px";
  }

  _onThumbPointerDown(e) {
    e.preventDefault();
    this._dragStartY = e.clientY;
    this._dragStartTop = parseFloat(this._thumbEl()?.style.top || "0");
    this._dragOnMove = (ev) => this._onThumbDrag(ev);
    this._dragOnUp = () => {
      window.removeEventListener("pointermove", this._dragOnMove);
      window.removeEventListener("pointerup", this._dragOnUp);
      this._dragOnMove = null;
      this._dragOnUp = null;
      this._dragStartY = null;
      this._dragStartTop = null;
    };
    window.addEventListener("pointermove", this._dragOnMove);
    window.addEventListener("pointerup", this._dragOnUp);
  }

  _onThumbDrag(e) {
    const log = this._logEl();
    const track = this._trackEl();
    if (!log || !track || this._dragStartY == null) return;
    const dy = e.clientY - this._dragStartY;
    const thumbHeight = this._thumbEl()?.offsetHeight || 0;
    const trackRange = track.clientHeight - thumbHeight;
    if (trackRange <= 0) return;
    const newTop = Math.max(0, Math.min(trackRange, this._dragStartTop + dy));
    const scrollRange = log.scrollHeight - log.clientHeight;
    log.scrollTop = (newTop / trackRange) * scrollRange;
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this._dragOnMove) {
      window.removeEventListener("pointermove", this._dragOnMove);
      window.removeEventListener("pointerup", this._dragOnUp);
    }
  }

  _snapToBottom() {
    this.autoScroll = true;
    this._scrollToBottom();
  }

  _stop() {
    if (this.stopping) return;
    this.stopping = true;
    this.dispatchEvent(new CustomEvent("stop"));
  }

  _dismiss() {
    this.dispatchEvent(new CustomEvent("dismiss"));
  }

  _displayLines() {
    if (this.finished) {
      // Show failure summary: everything from pytest's FAILURES/ERRORS separator onward.
      // Match pytest's separator format: "= FAILURES =" surrounded by = characters
      const failIdx = this.outputLines.findIndex(
        (l) => /^={2,}\s+(FAILURES|ERRORS)\s+={2,}/.test(l)
      );
      if (failIdx >= 0) {
        return this.outputLines.slice(failIdx);
      }
      // No failures — show the pytest summary line (e.g. "1 passed in 0.5s")
      const summaryIdx = this.outputLines.findLastIndex(
        (l) => /^={2,}\s+.*\d+\s+(passed|failed|error)/.test(l)
      );
      if (summaryIdx >= 0) {
        return this.outputLines.slice(summaryIdx);
      }
      return this.outputLines;
    }
    // During run: show only current test's output
    return this.outputLines.slice(this.currentTestStartIndex);
  }

  _lineClass(line) {
    if (line.includes(" PASSED")) return "pass";
    if (line.includes(" FAILED") || line.includes(" ERROR")) return "fail";
    return "";
  }

  render() {
    const p = this.progress || {};
    const r = this.result || {};
    const passedCount = p.passed || 0;
    const failedCount = p.failed || 0;
    const skippedCount = p.skipped || 0;
    const errorsCount = p.errors || 0;
    const completed = passedCount + failedCount + skippedCount + errorsCount;
    const total = p.total || 0;
    const progressText = total > 0 ? `${completed} / ${total}` : completed > 0 ? `${completed} / ?` : "";

    const passed = this.finished && (r.status === "passed" || ((r.failed || 0) === 0 && (r.passed || 0) > 0));

    return html`
      <header>
        <div class="header-left">
          <h1>${this.selectedDut}</h1>
          ${progressText
            ? html`<span class="progress-count">${progressText}</span>`
            : null}
        </div>
        <div class="header-right">
          ${this.finished
            ? html`
                <span class="result-badge ${passed ? "pass" : "fail"}">${passed ? "PASS" : "FAIL"}</span>
                <button
                  class="done-btn"
                  @pointerdown=${TouchFeedback.onPress}
                  @pointerup=${TouchFeedback.onRelease}
                  @pointerleave=${TouchFeedback.onRelease}
                  @click=${this._dismiss}
                >Done</button>
              `
            : html`<button
                class="stop-btn"
                ?disabled=${this.stopping}
                @pointerdown=${TouchFeedback.onPress}
                @pointerup=${TouchFeedback.onRelease}
                @pointerleave=${TouchFeedback.onRelease}
                @click=${this._stop}
              >${this.stopping ? "Stopping…" : "Stop"}</button>`
          }
        </div>
      </header>

      <div class="stats">
        <span class="stat-pass">${passedCount} passed</span>
        <span class="stat-fail ${failedCount > 0 ? "stat-fail--active" : ""}">${failedCount} failed</span>
        <span class="stat-skip">${skippedCount} skipped</span>
        <span class="stat-time">${Math.round(p.elapsed || r.elapsed || 0)}s</span>
      </div>

      ${!this.finished
        ? html`<div class="current-test">${p.current_test || ""}</div>`
        : null
      }

      <div class="log-container">
        <div class="log" @scroll=${this._onScroll}>
          ${this._displayLines().map(
            (line) =>
              html`<div class="log-line ${this._lineClass(line)}">${line}</div>`
          )}
        </div>
        <div class="log-scroll-track">
          <div class="log-scroll-thumb" @pointerdown=${this._onThumbPointerDown}></div>
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
