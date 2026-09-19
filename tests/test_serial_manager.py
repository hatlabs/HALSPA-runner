"""Tests for serial_manager module with mocked serial ports."""

import threading
import time
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
import serial

from halspa_runner.serial_manager import SerialManager, _PICO_VID, _PICO_PID, _UI_PICO_SERIAL


def _make_port_info(
    device: str = "/dev/ttyACM0",
    vid: int = _PICO_VID,
    pid: int = _PICO_PID,
    serial_number: str | None = None,
) -> MagicMock:
    """Create a mock ListPortInfo."""
    info = MagicMock()
    info.device = device
    info.vid = vid
    info.pid = pid
    info.serial_number = serial_number
    return info


@pytest.fixture
def mock_comports() -> Generator[MagicMock, None, None]:
    with patch("halspa_runner.serial_manager.serial.tools.list_ports.comports") as m:
        yield m


@pytest.fixture
def mock_serial_class() -> Generator[MagicMock, None, None]:
    with patch("halspa_runner.serial_manager.serial.Serial") as m:
        yield m


def test_discovers_ui_pico_by_serial_number(
    mock_comports: MagicMock, mock_serial_class: MagicMock,
) -> None:
    ui_port = _make_port_info(
        device="/dev/ttyACM0", serial_number=_UI_PICO_SERIAL,
    )
    mock_comports.return_value = [ui_port]

    mock_ser = MagicMock()
    mock_ser.readline.return_value = b""  # Reader thread will read empty
    mock_serial_class.return_value = mock_ser

    mgr = SerialManager()
    mgr._discover()

    assert mgr.ui_pico_connected
    args, kwargs = mock_serial_class.call_args
    assert args == ("/dev/ttyACM0", 115200)
    # Both timeouts must be finite: an untimed write blocks forever on a device
    # that has stopped draining the port.
    assert kwargs["timeout"] == pytest.approx(2.0, abs=1)
    assert kwargs["write_timeout"] > 0
    mgr.stop()


def test_probes_halspa_pico_with_id_command(
    mock_comports: MagicMock, mock_serial_class: MagicMock,
) -> None:
    halspa_port = _make_port_info(
        device="/dev/ttyACM1", serial_number="OTHER",
    )
    mock_comports.return_value = [halspa_port]

    mock_ser = MagicMock()
    mock_ser.readline.return_value = b"=== OK: ID HALPI2\n"
    mock_serial_class.return_value = mock_ser

    mgr = SerialManager()
    mgr._discover()

    assert mgr.halspa_pico_connected
    assert mgr.sandwich_type == "HALPI2"
    assert mgr.sandwich_detection_complete
    mock_ser.write.assert_called_with(b"ID\n")
    mgr.stop()


def test_no_picos_found(mock_comports: MagicMock) -> None:
    mock_comports.return_value = []

    mgr = SerialManager()
    mgr._discover()

    assert not mgr.ui_pico_connected
    assert not mgr.halspa_pico_connected
    assert mgr.sandwich_type is None
    assert mgr.sandwich_detection_complete
    mgr.stop()


def test_ignores_non_pico_usb_devices(mock_comports: MagicMock) -> None:
    # DUT USB device with different VID/PID
    dut_port = _make_port_info(device="/dev/ttyUSB0", vid=0x1234, pid=0x5678)
    mock_comports.return_value = [dut_port]

    mgr = SerialManager()
    mgr._discover()

    assert not mgr.ui_pico_connected
    assert not mgr.halspa_pico_connected
    mgr.stop()


def test_halspa_pico_no_id_response(
    mock_comports: MagicMock, mock_serial_class: MagicMock,
) -> None:
    port = _make_port_info(device="/dev/ttyACM1", serial_number="UNKNOWN")
    mock_comports.return_value = [port]

    mock_ser = MagicMock()
    # Simulate timeout: readline returns empty
    mock_ser.readline.return_value = b""
    mock_serial_class.return_value = mock_ser

    mgr = SerialManager()
    mgr._discover()

    assert not mgr.halspa_pico_connected
    assert mgr.sandwich_type is None
    assert mgr.sandwich_detection_complete
    mgr.stop()


def test_ui_reader_demuxes_events(
    mock_comports: MagicMock, mock_serial_class: MagicMock,
) -> None:
    ui_port = _make_port_info(
        device="/dev/ttyACM0", serial_number=_UI_PICO_SERIAL,
    )
    mock_comports.return_value = [ui_port]

    mock_ser = MagicMock()
    # Simulate: one button event then stop
    call_count = 0

    def readline_side_effect():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return b"=== EVENT: BUTTON_START\n"
        # Block briefly then return empty (reader will loop)
        time.sleep(0.1)
        return b""

    mock_ser.readline.side_effect = readline_side_effect
    mock_serial_class.return_value = mock_ser

    mgr = SerialManager()
    mgr._discover()

    # Give the reader thread time to process the event
    time.sleep(0.3)

    assert not mgr._event_queue.empty()
    event = mgr._event_queue.get_nowait()
    assert event == {"type": "button", "event": "BUTTON_START"}
    mgr.stop()


def test_send_ui_command_when_disconnected() -> None:
    mgr = SerialManager()
    result = mgr.send_ui_command("LED SOLID_GREEN")
    assert result is None
    mgr.stop()


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    """Poll until predicate holds. Bounded polling instead of fixed sleeps, so
    a slow or loaded machine does not turn a pass into a failure."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _pings(mock_ser: MagicMock) -> int:
    return sum(
        1 for call in mock_ser.write.call_args_list if call.args == (b"PING\n",)
    )


@pytest.fixture
def fast_watchdog() -> Generator[None, None, None]:
    """Ping after 0.05s of silence, stall after 2 unanswered pings."""
    with (
        patch("halspa_runner.serial_manager.config.UI_PICO_HEARTBEAT_INTERVAL", 0.05),
        patch("halspa_runner.serial_manager.config.UI_PICO_HEARTBEAT_MAX_MISSED", 2),
    ):
        yield


def _silent_ui_port(mock_serial_class: MagicMock) -> MagicMock:
    """A UI Pico that never sends anything and whose reader unblocks on close."""
    mock_ser = MagicMock()
    closed = threading.Event()

    def blocking_readline():
        # Long enough that the reader cannot rescue a test within its assertion
        # window: only an actual teardown closes the port and unblocks this.
        closed.wait(timeout=30)
        raise OSError("closed")

    mock_ser.readline.side_effect = blocking_readline
    mock_ser.close.side_effect = lambda: closed.set()
    mock_serial_class.return_value = mock_ser
    return mock_ser


def test_ui_watchdog_pings_idle_link_then_forces_reconnect(
    mock_comports: MagicMock, mock_serial_class: MagicMock, fast_watchdog: None,
) -> None:
    """A stalled link is detected, the slot is released and reconnect works.

    Asserting the manager state rather than just close() is what makes this
    test fail if the teardown stops clearing the slot — the regression from the
    linked issue, where /api/status kept reporting the UI Pico as connected.
    """
    ui_port = _make_port_info(
        device="/dev/ttyACM0", serial_number=_UI_PICO_SERIAL,
    )
    mock_comports.return_value = [ui_port]
    mock_ser = _silent_ui_port(mock_serial_class)

    mgr = SerialManager()
    mgr._discover()
    assert mgr.ui_pico_connected

    assert _wait_until(lambda: _pings(mock_ser) >= 1), "watchdog should PING an idle link"

    # No PONG ever arrives, so the unanswered count reaches the limit.
    assert _wait_until(lambda: not mgr.ui_pico_connected), (
        "stalled link must release the slot so the reconnect loop can reattach"
    )
    mock_ser.close.assert_called()

    events = []
    while not mgr._event_queue.empty():
        events.append(mgr._event_queue.get_nowait())
    assert {"type": "ui_pico_disconnected"} in events

    # The reconnect path must be able to reattach afterwards.
    mock_serial_class.return_value = _silent_ui_port(mock_serial_class)
    mgr._discover()
    assert mgr.ui_pico_connected
    mgr.stop()


def test_ui_watchdog_leaves_a_link_with_traffic_alone(
    mock_comports: MagicMock, mock_serial_class: MagicMock, fast_watchdog: None,
) -> None:
    """Incoming traffic must suppress the stall teardown.

    Without this, a watchdog that ignored received bytes would tear down a
    healthy link on every cycle — worse than the bug it fixes, because each
    reconnect drops button and e-stop events.
    """
    ui_port = _make_port_info(
        device="/dev/ttyACM0", serial_number=_UI_PICO_SERIAL,
    )
    mock_comports.return_value = [ui_port]

    mock_ser = MagicMock()
    mock_ser.readline.side_effect = lambda: (
        time.sleep(0.01) or b"=== EVENT: BUTTON_START\n"
    )
    mock_serial_class.return_value = mock_ser

    mgr = SerialManager()
    mgr._discover()

    # Several stall windows' worth of continuous traffic.
    time.sleep(0.05 * 6)
    assert mgr.ui_pico_connected, "a link carrying traffic must not be torn down"
    mock_ser.close.assert_not_called()
    assert _pings(mock_ser) == 0, "no PING is needed while bytes keep arriving"
    mgr.stop()


def test_ui_watchdog_pong_resets_the_unanswered_count(
    mock_comports: MagicMock, mock_serial_class: MagicMock, fast_watchdog: None,
) -> None:
    """A device answering PING stays connected however long it is idle."""
    ui_port = _make_port_info(
        device="/dev/ttyACM0", serial_number=_UI_PICO_SERIAL,
    )
    mock_comports.return_value = [ui_port]

    mock_ser = MagicMock()
    pinged = threading.Event()

    def readline():
        # Answer only after a PING, so the link is genuinely idle otherwise.
        if pinged.wait(timeout=0.5):
            pinged.clear()
            return b"=== OK: PONG\n"
        return b""

    def write(data):
        if data == b"PING\n":
            pinged.set()
        return len(data)

    mock_ser.readline.side_effect = readline
    mock_ser.write.side_effect = write
    mock_serial_class.return_value = mock_ser

    mgr = SerialManager()
    mgr._discover()

    assert _wait_until(lambda: _pings(mock_ser) >= 4), "watchdog should keep pinging"
    assert mgr.ui_pico_connected, "an answered PING must not count as a stall"
    mock_ser.close.assert_not_called()
    mgr.stop()


def test_pong_is_not_returned_as_a_command_response(
    mock_comports: MagicMock, mock_serial_class: MagicMock,
) -> None:
    """A watchdog PONG must not satisfy an unrelated send_ui_command.

    The response slot is a single unkeyed slot, so a PONG landing mid-command
    would otherwise be returned as that command's acknowledgement.
    """
    ui_port = _make_port_info(
        device="/dev/ttyACM0", serial_number=_UI_PICO_SERIAL,
    )
    mock_comports.return_value = [ui_port]

    mock_ser = MagicMock()
    lines = [b"=== OK: PONG\n", b"=== OK: LED\n"]

    def readline():
        if lines:
            time.sleep(0.02)
            return lines.pop(0)
        time.sleep(0.05)
        return b""

    mock_ser.readline.side_effect = readline
    mock_serial_class.return_value = mock_ser

    mgr = SerialManager()
    mgr._discover()

    result = mgr.send_ui_command("LED SOLID_GREEN")
    assert result == ["=== OK: LED"], (
        f"command must get its own reply, not the PONG; got {result}"
    )
    mgr.stop()


def test_ui_watchdog_tears_down_when_the_write_blocks(
    mock_comports: MagicMock, mock_serial_class: MagicMock, fast_watchdog: None,
) -> None:
    """A write that times out is itself a stall, not a reason to give up.

    A device that stops draining its CDC endpoint makes the PING write fail; if
    the watchdog simply returned, recovery would depend on the reader noticing,
    which is exactly what a stalled link prevents.
    """
    ui_port = _make_port_info(
        device="/dev/ttyACM0", serial_number=_UI_PICO_SERIAL,
    )
    mock_comports.return_value = [ui_port]
    mock_ser = _silent_ui_port(mock_serial_class)
    mock_ser.write.side_effect = serial.SerialTimeoutException("write timed out")

    mgr = SerialManager()
    mgr._discover()

    assert _wait_until(lambda: not mgr.ui_pico_connected), (
        "a failing write must force a reconnect"
    )
    assert _wait_until(
        lambda: not any(
            t.name == "ui-pico-watchdog" and t.is_alive()
            for t in threading.enumerate()
        )
    ), "watchdog thread must exit after tearing the connection down"
    mgr.stop()


def test_stop_reaps_threads_without_a_disconnect_event(
    mock_comports: MagicMock, mock_serial_class: MagicMock, fast_watchdog: None,
) -> None:
    """A clean shutdown is not a disconnect and must not stall."""
    ui_port = _make_port_info(
        device="/dev/ttyACM0", serial_number=_UI_PICO_SERIAL,
    )
    mock_comports.return_value = [ui_port]
    _silent_ui_port(mock_serial_class)

    mgr = SerialManager()
    mgr._discover()
    assert mgr.ui_pico_connected

    started = time.monotonic()
    mgr.stop()
    assert time.monotonic() - started < 2.0, "stop() must not wait out a join timeout"

    assert not any(
        t.name in ("ui-pico-reader", "ui-pico-watchdog") and t.is_alive()
        for t in threading.enumerate()
    )
    events = []
    while not mgr._event_queue.empty():
        events.append(mgr._event_queue.get_nowait())
    assert {"type": "ui_pico_disconnected"} not in events


def test_ui_reader_closes_port_on_disconnect(
    mock_comports: MagicMock, mock_serial_class: MagicMock,
) -> None:
    """A disconnect must release the file descriptor, not just drop the slot.

    The kernel keeps the /dev node alive while the fd is open, so leaking it
    on every re-enumeration accumulates dead descriptors.
    """
    ui_port = _make_port_info(
        device="/dev/ttyACM0", serial_number=_UI_PICO_SERIAL,
    )
    mock_comports.return_value = [ui_port]

    mock_ser = MagicMock()
    mock_ser.readline.side_effect = serial.SerialException("device disconnected")
    mock_serial_class.return_value = mock_ser

    mgr = SerialManager()
    mgr._discover()

    # Let the reader thread observe the disconnect and tear down.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and mgr.ui_pico_connected:
        time.sleep(0.01)

    assert not mgr.ui_pico_connected
    mock_ser.close.assert_called()
    mgr.stop()


def test_connect_does_not_publish_after_stop_has_begun(
    mock_comports: MagicMock, mock_serial_class: MagicMock,
) -> None:
    """A discovery in flight when stop() starts must not install a connection.

    stop() snapshots the slots, so anything published afterwards would keep its
    threads and its port alive past teardown.
    """
    ui_port = _make_port_info(
        device="/dev/ttyACM0", serial_number=_UI_PICO_SERIAL,
    )
    mock_comports.return_value = [ui_port]
    mock_ser = _silent_ui_port(mock_serial_class)

    mgr = SerialManager()
    mgr._stop_event.set()  # Shutdown already under way.
    mgr._discover()

    assert not mgr.ui_pico_connected
    mock_ser.close.assert_called()
    assert not any(
        t.name in ("ui-pico-reader", "ui-pico-watchdog") and t.is_alive()
        for t in threading.enumerate()
    )
