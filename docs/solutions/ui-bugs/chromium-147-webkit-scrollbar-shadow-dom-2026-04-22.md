---
title: "Chromium 147 ignores ::-webkit-scrollbar in Shadow DOM"
date: 2026-04-22
category: ui-bugs
module: halspa-runner
problem_type: ui_bug
component: frontend_lit
severity: high
symptoms:
  - "CSS scrollbar width/color changes have no visible effect on Pi kiosk"
  - "::-webkit-scrollbar pseudo-elements exist in shadow DOM but are not rendered"
  - "agent-browser (local Chrome) renders correctly; Pi Chromium 147 does not"
root_cause: browser_limitation
resolution_type: code_fix
tags:
  - chromium
  - webkit-scrollbar
  - shadow-dom
  - lit
  - kiosk
  - touchscreen
  - custom-scrollbar
---

# Chromium 147 ignores ::-webkit-scrollbar in Shadow DOM

## Problem

Scrollbar in the test runner log panel was too thin for touchscreen use. CSS changes to `::-webkit-scrollbar` pseudo-elements had zero visible effect on the Pi kiosk running Chromium 147, despite CDP confirming the rules existed in the shadow DOM's adopted stylesheets.

## Symptoms

- Scrollbar width set to 20px via `::-webkit-scrollbar { width: 20px }` — no change
- Custom thumb/track colors applied — not rendered
- `scrollbar-width: auto` explicitly set — no effect (defaults to `auto` anyway)
- Same CSS worked in local Chrome via agent-browser — different Chromium versions behave differently
- CDP `Runtime.evaluate` confirmed: rules present in `adoptedStyleSheets`, computed `scrollbarWidth: "auto"`, but native scrollbar rendered at default thin width

## What Didn't Work

1. **Removed `scrollbar-width: auto`** — hypothesized it conflicted with webkit pseudo-elements. No effect; computed value defaults to `auto` regardless.
2. **Changed webkit scrollbar colors** to brighter values (`#6b7685` thumb). CDP confirmed rules existed but weren't applied.
3. **Increased width** from 20px to 48px in `::-webkit-scrollbar`. No visual change.
4. **Tested via agent-browser** — showed custom scrollbar working. Misleading: agent-browser runs local Chrome (different version), not the Pi's Chromium 147.

## Solution

Replace `::-webkit-scrollbar` pseudo-elements with a custom scrollbar overlay:

```css
.log {
  scrollbar-width: none; /* Chromium 147 ignores ::-webkit-scrollbar; custom overlay below */
  overflow-y: auto;
  padding-right: 56px; /* Space for custom scrollbar */
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
}
```

JavaScript syncs thumb position and supports touch drag:

```javascript
// Cache elements — querySelector per scroll event (60Hz) is expensive
_logEl() { return this._cachedLog ??= this.shadowRoot?.querySelector(".log"); }
_trackEl() { return this._cachedTrack ??= this.shadowRoot?.querySelector(".log-scroll-track"); }
_thumbEl() { return this._cachedThumb ??= this.shadowRoot?.querySelector(".log-scroll-thumb"); }

_updateScrollThumb() {
  const log = this._logEl(), thumb = this._thumbEl(), track = this._trackEl();
  if (!log || !thumb || !track) return;
  const ratio = log.clientHeight / log.scrollHeight;
  if (ratio >= 1) { track.style.display = "none"; return; }
  track.style.display = "";
  const thumbHeight = Math.max(40, track.clientHeight * ratio);
  const trackRange = track.clientHeight - thumbHeight;
  if (trackRange <= 0) return;
  const thumbTop = (log.scrollTop / (log.scrollHeight - log.clientHeight)) * trackRange;
  thumb.style.height = thumbHeight + "px";
  thumb.style.top = thumbTop + "px";
}

// Touch drag via pointer events
_onThumbPointerDown(e) {
  e.preventDefault();
  this._dragStartY = e.clientY;
  this._dragStartTop = parseFloat(this._thumbEl()?.style.top || "0");
  // Store handlers for cleanup
  this._dragOnMove = (ev) => this._onThumbDrag(ev);
  this._dragOnUp = () => { /* remove listeners, clear state */ };
  window.addEventListener("pointermove", this._dragOnMove);
  window.addEventListener("pointerup", this._dragOnUp);
}

// Clean up on component disconnect (prevents listener leak)
disconnectedCallback() {
  super.disconnectedCallback();
  if (this._dragOnMove) {
    window.removeEventListener("pointermove", this._dragOnMove);
    window.removeEventListener("pointerup", this._dragOnUp);
  }
}
```

## Why This Works

Chromium 121+ deprecated `::-webkit-scrollbar` pseudo-elements in favor of the CSS Scrollbars spec (`scrollbar-width`, `scrollbar-color`). By Chromium 147, the pseudo-elements are completely ignored. However, `scrollbar-width: none` IS supported and successfully hides the native scrollbar, allowing a custom overlay to replace it with pixel-level width control.

Key implementation details:
- **`scrollbar-width: none` works** even though `::-webkit-scrollbar` doesn't — they use different code paths
- **Element caching** (`??=` nullish coalescing assignment) avoids 3x `querySelector` calls per scroll event at 60Hz
- **`trackRange <= 0` guard** prevents division by zero when thumb fills the entire track
- **`disconnectedCallback`** prevents window listener leak if component unmounts mid-drag
- **`touch-action: none`** on thumb prevents browser scroll interference during drag

## Prevention

- Do not use `::-webkit-scrollbar` pseudo-elements for new UI — they are deprecated in Chromium 121+
- For simple styling, use standard CSS: `scrollbar-width: auto|thin|none` and `scrollbar-color: <thumb> <track>`
- For pixel-level width control (touchscreen UIs), use custom scrollbar overlay pattern above
- Always test on the target browser version, not just local dev Chrome
- When debugging "CSS has no effect," use CDP to verify computed styles on the actual target browser, not a proxy

## Related Issues

- hatlabs/HALSPA-runner#22 — Original issue: scrollbar too thin for touch
- hatlabs/HALSPA-runner#33 — PR with the fix
