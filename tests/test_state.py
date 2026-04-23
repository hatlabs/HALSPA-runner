"""Tests for the application state machine."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from halspa_runner.state import AppState, StateMachine


@pytest.fixture
def serial() -> MagicMock:
    return MagicMock()


@pytest.fixture
def runner() -> MagicMock:
    mock = MagicMock()
    mock.is_running = False
    mock.cancel = AsyncMock()
    return mock


@pytest.fixture
def sm(serial: MagicMock, runner: MagicMock):
    # Patch threading.Timer inside state module so e-stop auto-clear timers
    # never actually run in unit tests — we assert scheduling and drive
    # auto-clear deterministically via _auto_clear_estop().
    with patch("halspa_runner.state.threading.Timer") as timer_cls:
        timer_cls.return_value = MagicMock()
        sm = StateMachine(serial_manager=serial, test_runner=runner)
        sm._test_timer_cls = timer_cls  # exposed for introspection
        yield sm


def test_initial_state(sm: StateMachine) -> None:
    assert sm.state == AppState.BOOTING


def test_set_ready(sm: StateMachine, serial: MagicMock) -> None:
    sm.set_ready()
    assert sm.state == AppState.IDLE
    serial.send_ui_command.assert_called_with("LED PULSE_WHITE")


def test_full_pass_flow(sm: StateMachine, serial: MagicMock) -> None:
    sm.set_ready()
    sm.select_dut("HALPI2")
    assert sm.state == AppState.DUT_SELECTED
    assert sm.selected_dut == "HALPI2"

    sm.start_running()
    assert sm.state == AppState.RUNNING
    serial.send_ui_command.assert_any_call("LED SOLID_YELLOW")
    serial.send_ui_command.assert_any_call("BUZZER START")

    sm.tests_completed(passed=True)
    assert sm.state == AppState.RESULTS_PASS
    serial.send_ui_command.assert_any_call("LED SOLID_GREEN")
    serial.send_ui_command.assert_any_call("BUZZER PASS")

    sm.dismiss_results()
    assert sm.state == AppState.DUT_SELECTED
    assert sm.selected_dut == "HALPI2"

    sm.deselect_dut()
    assert sm.state == AppState.IDLE
    assert sm.selected_dut is None


def test_full_fail_flow(sm: StateMachine, serial: MagicMock) -> None:
    sm.set_ready()
    sm.start_running()

    sm.tests_completed(passed=False)
    assert sm.state == AppState.RESULTS_FAIL
    serial.send_ui_command.assert_any_call("LED SOLID_RED")
    serial.send_ui_command.assert_any_call("BUZZER FAIL")


def test_estop_during_running_enters_estop(
    sm: StateMachine, serial: MagicMock, runner: MagicMock
) -> None:
    sm.set_ready()
    sm.start_running()
    runner.is_running = True

    sm.handle_estop()
    assert sm.state == AppState.ESTOP
    serial.send_ui_command.assert_any_call("LED BLINK_RED")
    serial.send_ui_command.assert_any_call("BUZZER ESTOP")


def test_estop_auto_clear_timer_is_armed(sm: StateMachine, runner: MagicMock) -> None:
    """handle_estop schedules an auto-clear timer with the configured delay."""
    from halspa_runner.state import ESTOP_AUTO_CLEAR_SECONDS

    sm.set_ready()
    runner.is_running = True
    sm.start_running()
    sm.handle_estop()

    sm._test_timer_cls.assert_called_once()
    delay_arg = sm._test_timer_cls.call_args.args[0]
    assert delay_arg == ESTOP_AUTO_CLEAR_SECONDS
    sm._test_timer_cls.return_value.start.assert_called_once()


def test_auto_clear_after_run_goes_to_results_fail(
    sm: StateMachine, serial: MagicMock, runner: MagicMock
) -> None:
    """Abort during a run counts as fail; no BUZZER FAIL follows the alarm."""
    sm.set_ready()
    sm.select_dut("HALPI2")
    sm.start_running()
    runner.is_running = True
    sm.handle_estop()

    serial.reset_mock()
    sm._auto_clear_estop()

    assert sm.state == AppState.RESULTS_FAIL
    # BUZZER OFF stops the alarm; no BUZZER FAIL after ESTOP.
    serial.send_ui_command.assert_any_call("BUZZER OFF")
    serial.send_ui_command.assert_any_call("LED SOLID_RED")
    for call in serial.send_ui_command.call_args_list:
        assert call.args[0] != "BUZZER FAIL"


def test_auto_clear_without_active_run_goes_to_idle(
    sm: StateMachine, serial: MagicMock
) -> None:
    """E-stop with no run in progress returns cleanly to idle, no fail state."""
    sm.set_ready()
    sm.select_dut("HALPI2")
    # runner.is_running is False by default
    sm.handle_estop()

    serial.reset_mock()
    sm._auto_clear_estop()

    assert sm.state == AppState.IDLE
    assert sm.selected_dut is None
    serial.send_ui_command.assert_any_call("LED PULSE_WHITE")
    serial.send_ui_command.assert_any_call("BUZZER OFF")


def test_tests_completed_during_estop_is_noop(
    sm: StateMachine, serial: MagicMock, runner: MagicMock
) -> None:
    """Runner cancel-callback during ESTOP must not steal the transition
    or emit BUZZER FAIL; the ESTOP auto-clear owns the outcome.
    """
    sm.set_ready()
    runner.is_running = True
    sm.start_running()
    sm.handle_estop()
    serial.reset_mock()

    sm.tests_completed(passed=False)

    assert sm.state == AppState.ESTOP
    for call in serial.send_ui_command.call_args_list:
        assert call.args[0] != "BUZZER FAIL"


def test_tests_completed_after_auto_clear_is_noop(
    sm: StateMachine, serial: MagicMock, runner: MagicMock
) -> None:
    """Cancel callback can arrive after the auto-clear timer has already
    transitioned to RESULTS_FAIL (cancel path's SIGTERM wait + SIGKILL can
    exceed the 2.5 s timer budget). In that case, tests_completed must not
    re-emit BUZZER FAIL over the ESTOP alarm that just finished.
    """
    sm.set_ready()
    runner.is_running = True
    sm.start_running()
    sm.handle_estop()
    sm._auto_clear_estop()
    assert sm.state == AppState.RESULTS_FAIL
    serial.reset_mock()

    sm.tests_completed(passed=False)

    assert sm.state == AppState.RESULTS_FAIL
    for call in serial.send_ui_command.call_args_list:
        assert call.args[0] != "BUZZER FAIL"


def test_repeat_estop_after_auto_clear_rearms_timer(
    sm: StateMachine, runner: MagicMock
) -> None:
    """After auto-clear to RESULTS_FAIL, a fresh e-stop must arm a new
    timer and transition to ESTOP again.
    """
    sm.set_ready()
    runner.is_running = True
    sm.start_running()
    sm.handle_estop()
    sm._auto_clear_estop()
    assert sm.state == AppState.RESULTS_FAIL
    runner.is_running = False

    sm.handle_estop()

    assert sm.state == AppState.ESTOP
    assert sm._test_timer_cls.call_count == 2


def test_duplicate_estop_ignored(sm: StateMachine, serial: MagicMock) -> None:
    sm.set_ready()
    sm.handle_estop()
    serial.reset_mock()

    sm.handle_estop()  # Second e-stop should be ignored
    serial.send_ui_command.assert_not_called()


def test_manual_clear_cancels_pending_timer(sm: StateMachine) -> None:
    sm.set_ready()
    sm.handle_estop()
    timer = sm._test_timer_cls.return_value

    sm.clear_estop()

    timer.cancel.assert_called_once()
    assert sm.state == AppState.IDLE
    assert sm.selected_dut is None


def test_clear_estop_is_safe_net_outside_estop(sm: StateMachine) -> None:
    """Calling clear_estop while not in ESTOP is a no-op."""
    sm.set_ready()
    sm.clear_estop()
    assert sm.state == AppState.IDLE


def test_state_change_callback(sm: StateMachine) -> None:
    changes: list[tuple[AppState, AppState]] = []
    sm.on_state_change(lambda old, new: changes.append((old, new)))

    sm.set_ready()
    sm.select_dut("HALPI2")

    assert len(changes) == 2
    assert changes[0] == (AppState.BOOTING, AppState.IDLE)
    assert changes[1] == (AppState.IDLE, AppState.DUT_SELECTED)


def test_no_serial_manager(runner: MagicMock) -> None:
    with patch("halspa_runner.state.threading.Timer"):
        sm = StateMachine(serial_manager=None, test_runner=runner)
    # Should not raise when sending LED commands without serial
    sm.set_ready()
    sm.start_running()
    sm.tests_completed(passed=True)
    assert sm.state == AppState.RESULTS_PASS


def test_set_targets(sm: StateMachine) -> None:
    sm.set_ready()
    sm.select_dut("HALPI2", Path("/tmp/HALPI2-tests"))

    sm.set_targets(["tests/100_power/test_rails.py"])

    assert sm.selected_targets == ["tests/100_power/test_rails.py"]


def test_deselect_dut_clears_all(sm: StateMachine) -> None:
    sm.set_ready()
    sm.select_dut("HALPI2", Path("/tmp/HALPI2-tests"))
    sm.set_targets(["tests/100_power"])

    sm.deselect_dut()

    assert sm.selected_dut is None
    assert sm.selected_repo_path is None
    assert sm.selected_targets is None
    assert sm.state == AppState.IDLE


def test_dismiss_preserves_dut_and_targets(sm: StateMachine) -> None:
    sm.set_ready()
    sm.select_dut("HALPI2", Path("/tmp/HALPI2-tests"))
    sm.set_targets(["tests/100_power"])
    sm.start_running()
    sm.tests_completed(passed=True)

    sm.dismiss_results()

    assert sm.selected_dut == "HALPI2"
    assert sm.selected_targets == ["tests/100_power"]
    assert sm.state == AppState.DUT_SELECTED


def test_select_dut_stores_repo_path(sm: StateMachine) -> None:
    sm.set_ready()
    repo = Path("/tmp/HALPI2-tests")

    sm.select_dut("HALPI2", repo)

    assert sm.selected_repo_path == repo
    assert sm.selected_dut == "HALPI2"
    assert sm.state == AppState.DUT_SELECTED
