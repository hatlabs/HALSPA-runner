"""Tests for serial_manager module with mocked serial ports."""

import threading
import time
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

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
    mock_serial_class.assert_called_once_with(
        "/dev/ttyACM0", 115200, timeout=pytest.approx(2.0, abs=1),
    )
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
