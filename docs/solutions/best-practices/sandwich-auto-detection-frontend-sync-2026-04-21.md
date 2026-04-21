---
title: "Hardware Sandwich Auto-Detection with Frontend State Sync"
date: 2026-04-21
category: best-practices
module: halspa-runner
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - Backend detects hardware type at startup and frontend must reflect it
  - UI options should be constrained to match connected hardware
  - Auto-navigation to the correct screen reduces operator friction
tags:
  - websocket
  - sandwich-detection
  - frontend-state
  - auto-navigation
  - hardware-detection
  - lit-js
---

# Hardware Sandwich Auto-Detection with Frontend State Sync

## Context

HALSPA-runner's backend detected sandwich type via serial (Pico ID command) at startup, but never communicated it to the frontend. The `sandwichType` property in the UI was always null. All DUT buttons remained enabled regardless of connected hardware, letting operators select test suites they couldn't run.

## Guidance

Three components: backend broadcast, frontend extraction + auto-navigation, conditional UI rendering.

### Backend: Include hardware type in all WebSocket state messages

Add the detected type to every `state_change` message — both the broadcast callback and the initial handshake. This ensures the frontend receives it on first connect and on every state transition:

```python
# on_state_change callback
msg = {
    "type": "state_change",
    "state": new.value,
    "old_state": old.value,
    "sandwich_type": serial_manager.sandwich_type if serial_manager else None,
}

# Initial WS handshake
await ws.send_json({
    "type": "state_change",
    "state": state_machine.state.value,
    "old_state": None,
    "sandwich_type": serial_manager.sandwich_type if serial_manager else None,
})
```

Including it in every message is simpler than a separate message type and avoids the frontend needing to poll `/api/status`.

### Frontend: Extract and auto-select

Extract `sandwich_type` from incoming WS messages. Auto-navigate to the matching DUT once when conditions are met:

```javascript
// In _onMessage handler:
if (data.sandwich_type !== undefined) {
    this.sandwichType = data.sandwich_type;
}

// Called after DUT list loads:
_tryAutoSelectSandwich() {
    if (this._hasAutoSelected || !this.sandwichType || this.selectedDut) return;
    if (this.state !== "idle") return;
    const match = this.duts.find((d) => d.name === this.sandwichType);
    if (match) {
        this._hasAutoSelected = true;
        this._onSelectDut({ detail: { dut: match.name } });
    }
}
```

The `_hasAutoSelected` guard fires once per session — sandwich changes require power off, so startup detection is sufficient. Returning to the menu manually doesn't re-trigger auto-select.

### Frontend: Disable non-matching options with error feedback

All DUT buttons disabled unless they match the detected sandwich. Three states need distinct rendering:

```javascript
// Disable logic — simple equality check handles all cases:
// null sandwich → nothing matches → all disabled
// unknown sandwich → nothing matches → all disabled
// known sandwich → only match enabled
?disabled=${this.sandwichType !== dut.name}

// Status messages for the two error cases:
_renderStatusMessage() {
    if (!this.sandwichType) {
        return html`<div class="status-msg error">No sandwich detected</div>`;
    }
    const known = this.duts.some((d) => d.name === this.sandwichType);
    if (!known) {
        return html`<div class="status-msg error">Unknown sandwich: ${this.sandwichType}</div>`;
    }
    return null;
}
```

### Name matching convention

Pico firmware returns the type as an uppercase string (e.g., `=== OK: ID HALPI2`). Test directories follow the pattern `<name>-tests` and are normalized: strip `-tests`, uppercase. Match is exact string equality.

## Why This Matters

- **Prevents invalid selections**: Operators can't start tests against hardware that isn't connected
- **Reduces friction**: Auto-navigation skips the menu entirely for the common single-sandwich case
- **Clear error feedback**: "No sandwich detected" vs "Unknown sandwich: FOO" are different problems requiring different actions
- **Timing correctness**: JS event loop guarantees `sandwichType` is set before `_tryAutoSelectSandwich` runs after `_fetchDuts` completes, regardless of message arrival order

## When to Apply

- Backend detects a hardware characteristic (type, revision, firmware version) at startup
- Frontend has multiple options where only some are valid for the detected hardware
- Detection happens once at startup (not hot-swappable)
- Users should be guided to the correct option, not blocked from seeing alternatives

## Examples

The pattern generalizes to any hardware-gated UI. The key structure is always:
1. Backend detects → includes in state messages
2. Frontend extracts → auto-selects if unique match
3. UI disables non-matching options → shows why

## Related

- [Lit selection state preservation](../best-practices/lit-preserve-selection-state-across-screen-transitions.md) — complementary pattern for preserving user selections across screen transitions
- hatlabs/HALSPA-runner#21 — PR implementing this pattern
