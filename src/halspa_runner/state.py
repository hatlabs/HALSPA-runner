"""Application state machine with e-stop logic and optional I2C power control."""

import logging
import threading
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .serial_manager import SerialManager
    from .test_runner import PytestRunner

logger = logging.getLogger(__name__)

# E-stop modal is transient: the ESTOP buzzer runs ~2 s, then we hold a short
# beat before auto-clearing so the blink-red LED is unmistakable.
ESTOP_AUTO_CLEAR_SECONDS = 2.5


class AppState(Enum):
    BOOTING = "booting"
    IDLE = "idle"
    DUT_SELECTED = "dut_selected"
    RUNNING = "running"
    RESULTS_PASS = "results_pass"
    RESULTS_FAIL = "results_fail"
    ESTOP = "estop"


# LED commands sent to UI Pico on state transitions
_STATE_LED: dict[AppState, str] = {
    AppState.BOOTING: "LED OFF",
    AppState.IDLE: "LED PULSE_WHITE",
    AppState.DUT_SELECTED: "LED PULSE_WHITE",
    AppState.RUNNING: "LED SOLID_YELLOW",
    AppState.RESULTS_PASS: "LED SOLID_GREEN",
    AppState.RESULTS_FAIL: "LED SOLID_RED",
    AppState.ESTOP: "LED BLINK_RED",
}


class StateMachine:
    """Central state machine coordinating the runner application.

    The e-stop handler is designed to be called from the serial manager's
    reader thread (not async) so it works independently of the event loop.
    """

    def __init__(
        self,
        serial_manager: "SerialManager | None" = None,
        test_runner: "PytestRunner | None" = None,
    ) -> None:
        self._state = AppState.BOOTING
        self._serial = serial_manager
        self._runner = test_runner
        self._on_state_change: list[Any] = []
        self._selected_dut: str | None = None
        self._selected_repo_path: Path | None = None
        self._selected_targets: list[str] | None = None
        self._power_control_available = False
        self._estop_power_off_failed = False
        self._estop_run_was_active = False
        self._estop_clear_timer: threading.Timer | None = None
        # Serialises the ESTOP lifecycle (handle / auto-clear / manual clear)
        # so the timer thread and the async event loop can't interleave their
        # transitions. Other state transitions don't touch ESTOP and don't
        # need this lock.
        self._estop_lock = threading.Lock()

        # Check if halspa library is available for e-stop power control
        try:
            import halspa  # noqa: F401
            self._power_control_available = True
        except ImportError:
            logger.info("halspa library not available — e-stop will skip I2C power-off")

    @property
    def state(self) -> AppState:
        return self._state

    @property
    def selected_dut(self) -> str | None:
        return self._selected_dut

    @property
    def selected_repo_path(self) -> Path | None:
        return self._selected_repo_path

    @property
    def selected_targets(self) -> list[str] | None:
        return self._selected_targets

    @property
    def estop_power_off_failed(self) -> bool:
        return self._estop_power_off_failed

    def on_state_change(self, callback: Any) -> None:
        """Register a callback for state changes: callback(old_state, new_state)."""
        self._on_state_change.append(callback)

    def transition(self, new_state: AppState) -> bool:
        """Attempt a state transition. Returns True if transition occurred."""
        old = self._state
        if old == new_state:
            return False

        self._state = new_state
        logger.info("State: %s -> %s", old.value, new_state.value)

        # Send LED command for new state
        led_cmd = _STATE_LED.get(new_state)
        if led_cmd and self._serial:
            self._serial.send_ui_command(led_cmd)

        for cb in self._on_state_change:
            try:
                cb(old, new_state)
            except Exception:
                logger.exception("State change callback error")

        return True

    def set_ready(self) -> None:
        """Called when all subsystems are initialized."""
        self.transition(AppState.IDLE)

    def select_dut(self, dut_name: str, repo_path: Path | None = None) -> None:
        """Select a DUT for testing."""
        self._selected_dut = dut_name
        if repo_path is not None:
            self._selected_repo_path = repo_path
        self._selected_targets = None
        self.transition(AppState.DUT_SELECTED)

    def set_targets(self, targets: list[str] | None) -> None:
        """Update the selected test targets (synced from frontend)."""
        self._selected_targets = targets

    def deselect_dut(self) -> None:
        """Clear DUT selection and return to idle (back to main menu)."""
        self._selected_dut = None
        self._selected_repo_path = None
        self._selected_targets = None
        self.transition(AppState.IDLE)

    def start_running(self) -> None:
        """Transition to RUNNING when tests begin."""
        self.transition(AppState.RUNNING)
        if self._serial:
            self._serial.send_ui_command("BUZZER START")

    def tests_completed(self, passed: bool) -> None:
        """Called when pytest finishes."""
        # Only act when we are actually in RUNNING. If the e-stop handler
        # already moved us out of RUNNING (ESTOP, or RESULTS_FAIL once the
        # auto-clear timer has fired), the ESTOP auto-clear owns the outcome
        # and the ESTOP buzzer is the only cue — don't overlap it with
        # BUZZER FAIL or re-emit state.
        if self._state != AppState.RUNNING:
            return
        if passed:
            self.transition(AppState.RESULTS_PASS)
            if self._serial:
                self._serial.send_ui_command("BUZZER PASS")
        else:
            self.transition(AppState.RESULTS_FAIL)
            if self._serial:
                self._serial.send_ui_command("BUZZER FAIL")

    def dismiss_results(self) -> None:
        """Dismiss results, preserving DUT and targets for re-run."""
        self.transition(AppState.DUT_SELECTED)

    def handle_estop(self, runner_cancel_coro: Any = None) -> None:
        """Handle e-stop: kill tests, disable power. Thread-safe.

        This is called from the serial manager's reader thread, not from
        the async event loop, so it can respond even if the event loop is busy.

        Args:
            runner_cancel_coro: If provided, an asyncio loop is used to schedule
                               the cancellation. Otherwise, the runner is cancelled
                               via its synchronous interface if available.
        """
        with self._estop_lock:
            if self._state == AppState.ESTOP:
                return  # Already in e-stop, ignore duplicate
            self._estop_power_off_failed = False
            self._estop_run_was_active = bool(
                self._runner and self._runner.is_running
            )
            self.transition(AppState.ESTOP)

        # Buzzer alarm
        if self._serial:
            self._serial.send_ui_command("BUZZER ESTOP")

        # Kill running test process
        if self._runner and self._runner.is_running:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.run_coroutine_threadsafe(self._runner.cancel(), loop)
                else:
                    loop.run_until_complete(self._runner.cancel())
            except RuntimeError:
                logger.warning("Could not cancel test runner from e-stop thread")

        # I2C power-off (only after test process is killed)
        self._emergency_power_off()

        # Schedule auto-clear. The ESTOP modal is a transient alert, not a
        # safety-gated interlock — the operator is not required to acknowledge.
        self._arm_auto_clear()

    def _arm_auto_clear(self, delay: float | None = None) -> None:
        # Resolve the delay at call time so tests/tuning that monkeypatch the
        # module constant take effect.
        if delay is None:
            delay = ESTOP_AUTO_CLEAR_SECONDS
        if self._estop_clear_timer is not None:
            self._estop_clear_timer.cancel()
        t = threading.Timer(delay, self._auto_clear_estop)
        t.daemon = True
        self._estop_clear_timer = t
        t.start()

    def _auto_clear_estop(self) -> None:
        """Timer callback. Transitions out of ESTOP to RESULTS_FAIL or IDLE."""
        with self._estop_lock:
            self._estop_clear_timer = None
            if self._state != AppState.ESTOP:
                return
            if self._serial:
                self._serial.send_ui_command("BUZZER OFF")
            if self._estop_run_was_active:
                # Abort counts as fail. No BUZZER FAIL — the ESTOP alarm was the cue.
                self.transition(AppState.RESULTS_FAIL)
            else:
                # No run was in progress; drop all selection and return to idle.
                self._selected_dut = None
                self._selected_repo_path = None
                self._selected_targets = None
                self.transition(AppState.IDLE)

    def clear_estop(self) -> None:
        """Manual recovery path. Normally e-stop auto-clears; this is used
        only when the UI surfaces a Force-clear control after an I2C
        power-off failure (or as a safety net if the timer misfires).
        Performs a hard reset of selection.
        """
        with self._estop_lock:
            if self._state != AppState.ESTOP:
                return
            if self._estop_clear_timer is not None:
                self._estop_clear_timer.cancel()
                self._estop_clear_timer = None
            self._selected_dut = None
            self._selected_repo_path = None
            self._selected_targets = None
            self._estop_power_off_failed = False
            self._estop_run_was_active = False
            if self._serial:
                self._serial.send_ui_command("BUZZER OFF")
            self.transition(AppState.IDLE)

    def _emergency_power_off(self) -> None:
        """Disable all power via I2C. Called during e-stop."""
        if not self._power_control_available:
            logger.warning("Skipping I2C power-off — halspa library not available")
            return

        try:
            from halspa.board import HalspaBoard
            board = HalspaBoard()
            board.power.disable_all()
            board.close()
            logger.info("E-stop: I2C power disabled")
        except Exception:
            logger.exception("E-stop: I2C power-off FAILED")
            self._estop_power_off_failed = True
