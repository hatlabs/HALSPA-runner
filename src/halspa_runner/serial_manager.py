"""Serial communication with UI Pico and HALSPA Pico over USB CDC.

Runs a dedicated reader thread per connected Pico. The UI Pico is identified
by its USB serial number "HALSPA-UI". The HALSPA Pico is identified by probing
remaining CDC devices with the ID command.
"""

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import serial
import serial.tools.list_ports
from serial.tools.list_ports_common import ListPortInfo

from . import config

logger = logging.getLogger(__name__)

# USB identifiers for Pico 2 CDC devices
_PICO_VID = 0x2E8A
_PICO_PID = 0x000A

# USB serial number that identifies the UI Pico
_UI_PICO_SERIAL = "HALSPA-UI"


@dataclass
class PicoConnection:
    """State for a single serial connection to a Pico."""

    port: serial.Serial
    device: str
    reader_thread: threading.Thread | None = None
    stop_event: threading.Event = field(default_factory=threading.Event)


class SerialManager:
    """Manages serial connections to the UI Pico and HALSPA Pico.

    Events from buttons and state changes are placed on an asyncio-safe queue
    for the FastAPI event loop to consume.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self._loop = loop
        self._event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._ui_pico: PicoConnection | None = None
        self._halspa_pico: PicoConnection | None = None
        self._sandwich_type: str | None = None
        self._sandwich_detection_complete = False
        self._lock = threading.Lock()
        self._reconnect_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        # Pending command response slot (for synchronous command/response)
        self._ui_response: threading.Event = threading.Event()
        self._ui_response_lines: list[str] = []

    @property
    def ui_pico_connected(self) -> bool:
        return self._ui_pico is not None

    @property
    def halspa_pico_connected(self) -> bool:
        return self._halspa_pico is not None

    @property
    def sandwich_type(self) -> str | None:
        return self._sandwich_type

    @property
    def sandwich_detection_complete(self) -> bool:
        return self._sandwich_detection_complete

    def start(self) -> None:
        """Discover Picos and start reader threads."""
        self._discover()
        self._reconnect_thread = threading.Thread(
            target=self._reconnect_loop, daemon=True, name="serial-reconnect",
        )
        self._reconnect_thread.start()

    def stop(self) -> None:
        """Stop all threads and close serial ports."""
        self._stop_event.set()
        if self._ui_pico:
            self._ui_pico.stop_event.set()
        if self._halspa_pico:
            self._halspa_pico.stop_event.set()
        if self._reconnect_thread:
            self._reconnect_thread.join(timeout=3)
        with self._lock:
            if self._ui_pico:
                self._close_pico(self._ui_pico)
                self._ui_pico = None
            if self._halspa_pico:
                self._close_pico(self._halspa_pico)
                self._halspa_pico = None

    def send_ui_command(self, cmd: str) -> list[str] | None:
        """Send a command to the UI Pico and wait for response.

        Returns response lines or None if UI Pico is not connected.
        Thread-safe.
        """
        with self._lock:
            pico = self._ui_pico
        if pico is None:
            return None

        self._ui_response.clear()
        self._ui_response_lines.clear()

        try:
            pico.port.write(f"{cmd}\n".encode())
            pico.port.flush()
        except (serial.SerialException, OSError):
            logger.warning("Failed to send command to UI Pico")
            return None

        # Wait for response from reader thread
        if self._ui_response.wait(timeout=config.SERIAL_TIMEOUT):
            return list(self._ui_response_lines)
        logger.warning("UI Pico command '%s' timed out", cmd)
        return None

    def _put_event(self, event: dict[str, Any]) -> None:
        """Put an event on the queue (thread-safe for asyncio)."""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._event_queue.put_nowait, event)
        else:
            try:
                self._event_queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Event queue full, dropping event: %s", event)

    async def get_event(self) -> dict[str, Any]:
        """Wait for the next event (async)."""
        return await self._event_queue.get()

    def _discover(self) -> None:
        """Scan USB serial ports for Picos."""
        ports = serial.tools.list_ports.comports()
        pico_ports: list[ListPortInfo] = [
            p for p in ports if p.vid == _PICO_VID and p.pid == _PICO_PID
        ]

        for port_info in pico_ports:
            if port_info.serial_number == _UI_PICO_SERIAL:
                with self._lock:
                    if self._ui_pico is not None:
                        continue
                    # Claim the slot to prevent races with reconnect thread
                    self._ui_pico = True  # type: ignore[assignment]
                self._connect_ui_pico(port_info)
            else:
                with self._lock:
                    if self._halspa_pico is not None:
                        continue
                    self._halspa_pico = True  # type: ignore[assignment]
                self._probe_halspa_pico(port_info)

        if not self._ui_pico:
            logger.warning("UI Pico not found — physical controls unavailable")
        if not self._halspa_pico:
            logger.warning("HALSPA Pico not found — sandwich type unknown")

        if not self._sandwich_detection_complete:
            self._sandwich_detection_complete = True
            self._put_event({"type": "sandwich_detection_complete", "sandwich_type": self._sandwich_type})

    def _connect_ui_pico(self, port_info: ListPortInfo) -> None:
        """Open connection to the UI Pico and start reader thread."""
        try:
            ser = serial.Serial(
                port_info.device, 115200, timeout=config.SERIAL_TIMEOUT,
            )
            ser.reset_input_buffer()
        except serial.SerialException:
            logger.warning("Failed to open UI Pico at %s", port_info.device)
            with self._lock:
                self._ui_pico = None
            return

        conn = PicoConnection(port=ser, device=port_info.device)
        conn.reader_thread = threading.Thread(
            target=self._ui_reader_loop, args=(conn,),
            daemon=True, name="ui-pico-reader",
        )
        conn.reader_thread.start()

        with self._lock:
            self._ui_pico = conn
        logger.info("UI Pico connected at %s", port_info.device)

    def _probe_halspa_pico(self, port_info: ListPortInfo) -> None:
        """Try to identify a HALSPA Pico by sending the ID command."""
        try:
            ser = serial.Serial(port_info.device, 115200, timeout=1.0)
            ser.reset_input_buffer()
            time.sleep(0.1)  # Let the device settle
            ser.write(b"ID\n")
            ser.flush()

            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                raw = ser.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace").strip()
                if line.startswith("=== OK: ID "):
                    sandwich_id = line.removeprefix("=== OK: ID ").strip()
                    self._sandwich_type = sandwich_id
                    conn = PicoConnection(port=ser, device=port_info.device)
                    with self._lock:
                        self._halspa_pico = conn
                    logger.info(
                        "HALSPA Pico found at %s, sandwich: %s",
                        port_info.device, sandwich_id,
                    )
                    self._put_event({"type": "sandwich_detected", "sandwich_type": sandwich_id})
                    return
            # No valid ID response — not a HALSPA Pico
            ser.close()
            with self._lock:
                self._halspa_pico = None
        except serial.SerialException:
            with self._lock:
                self._halspa_pico = None

    def _ui_reader_loop(self, conn: PicoConnection) -> None:
        """Read lines from UI Pico, demux events vs command responses."""
        while not conn.stop_event.is_set():
            try:
                raw = conn.port.readline()
            except (serial.SerialException, OSError):
                logger.warning("UI Pico disconnected")
                with self._lock:
                    self._ui_pico = None
                self._put_event({"type": "ui_pico_disconnected"})
                return

            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            if line.startswith("=== EVENT: "):
                event_name = line.removeprefix("=== EVENT: ").strip()
                self._put_event({"type": "button", "event": event_name})
            elif line.startswith("=== OK:") or line.startswith("=== ERROR:"):
                self._ui_response_lines.append(line)
                self._ui_response.set()
            elif line.startswith("=== INFO:"):
                logger.debug("UI Pico info: %s", line)

    def _reconnect_loop(self) -> None:
        """Periodically try to reconnect missing Picos."""
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=config.SERIAL_RECONNECT_INTERVAL)
            if self._stop_event.is_set():
                break
            with self._lock:
                need_ui = self._ui_pico is None
                need_halspa = self._halspa_pico is None
            if need_ui or need_halspa:
                self._discover()

    @staticmethod
    def _close_pico(conn: PicoConnection) -> None:
        conn.stop_event.set()
        try:
            conn.port.close()
        except (serial.SerialException, OSError):
            pass
        if conn.reader_thread:
            conn.reader_thread.join(timeout=2)
