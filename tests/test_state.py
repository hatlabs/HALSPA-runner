"""Tests for the application state machine."""

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
def sm(serial: MagicMock, runner: MagicMock) -> StateMachine:
    return StateMachine(serial_manager=serial, test_runner=runner)


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
    assert sm.state == AppState.IDLE
    assert sm.selected_dut is None


def test_full_fail_flow(sm: StateMachine, serial: MagicMock) -> None:
    sm.set_ready()
    sm.start_running()

    sm.tests_completed(passed=False)
    assert sm.state == AppState.RESULTS_FAIL
    serial.send_ui_command.assert_any_call("LED SOLID_RED")
    serial.send_ui_command.assert_any_call("BUZZER FAIL")


def test_estop_during_running(sm: StateMachine, serial: MagicMock, runner: MagicMock) -> None:
    sm.set_ready()
    sm.start_running()
    runner.is_running = True

    sm.handle_estop()
    assert sm.state == AppState.ESTOP
    serial.send_ui_command.assert_any_call("LED BLINK_RED")
    serial.send_ui_command.assert_any_call("BUZZER ESTOP")


def test_estop_when_not_running(sm: StateMachine) -> None:
    sm.set_ready()
    sm.handle_estop()
    assert sm.state == AppState.ESTOP


def test_duplicate_estop_ignored(sm: StateMachine, serial: MagicMock) -> None:
    sm.set_ready()
    sm.handle_estop()
    serial.reset_mock()

    sm.handle_estop()  # Second e-stop should be ignored
    serial.send_ui_command.assert_not_called()


def test_clear_estop(sm: StateMachine) -> None:
    sm.set_ready()
    sm.handle_estop()
    assert sm.state == AppState.ESTOP

    sm.clear_estop()
    assert sm.state == AppState.IDLE
    assert sm.selected_dut is None


def test_state_change_callback(sm: StateMachine) -> None:
    changes: list[tuple[AppState, AppState]] = []
    sm.on_state_change(lambda old, new: changes.append((old, new)))

    sm.set_ready()
    sm.select_dut("HALPI2")

    assert len(changes) == 2
    assert changes[0] == (AppState.BOOTING, AppState.IDLE)
    assert changes[1] == (AppState.IDLE, AppState.DUT_SELECTED)


def test_no_serial_manager(runner: MagicMock) -> None:
    sm = StateMachine(serial_manager=None, test_runner=runner)
    # Should not raise when sending LED commands without serial
    sm.set_ready()
    sm.start_running()
    sm.tests_completed(passed=True)
    assert sm.state == AppState.RESULTS_PASS
