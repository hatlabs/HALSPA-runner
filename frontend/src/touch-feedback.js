/**
 * Static helpers for reliable touch feedback on buttons.
 *
 * CSS :active is too brief on touchscreens (~50ms). These add a .pressed
 * class on pointerdown with a minimum visible duration of 120ms, ensuring
 * every tap is visually acknowledged.
 *
 * Usage:
 *   <button @pointerdown=${TouchFeedback.onPress}
 *           @pointerup=${TouchFeedback.onRelease}
 *           @pointerleave=${TouchFeedback.onRelease}>
 */

const MIN_PRESS_MS = 120;

export class TouchFeedback {
  static onPress(e) {
    const el = e.currentTarget;
    el.classList.add("pressed");
    el._pressedAt = Date.now();
    // Fallback cleanup: if pointerup/leave never fires (e.g., element disabled
    // after pointerdown), remove pressed class via a document-level listener.
    const cleanup = () => {
      el.classList.remove("pressed");
      document.removeEventListener("pointerup", cleanup);
      document.removeEventListener("pointercancel", cleanup);
    };
    document.addEventListener("pointerup", cleanup, { once: true });
    document.addEventListener("pointercancel", cleanup, { once: true });
  }

  static onRelease(e) {
    const el = e.currentTarget;
    const elapsed = Date.now() - (el._pressedAt || 0);
    const remaining = Math.max(0, MIN_PRESS_MS - elapsed);

    if (remaining > 0) {
      setTimeout(() => el.classList.remove("pressed"), remaining);
    } else {
      el.classList.remove("pressed");
    }
  }

}

/**
 * Shared CSS for pressed and disabled button states.
 * Import into component static styles via css tag.
 */
export const buttonFeedbackStyles = `
  button.pressed {
    opacity: 0.7;
    transform: scale(0.97);
  }

  button[disabled] {
    opacity: 0.5;
    pointer-events: none;
  }

  button {
    transition: opacity 0.1s, transform 0.1s, background 0.15s;
  }
`;
