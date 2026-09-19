"""Serial communication with UI Pico and HALSPA Pico over USB CDC.

The UI Pico is identified by its USB serial number "HALSPA-UI" and gets two
threads: a reader that demuxes incoming lines, and a watchdog that detects a
stalled CDC link. It carries the start button, the e-stop and the buzzer, so a
silently dead link there loses operator input.

The HALSPA Pico is identified by probing the remaining CDC devices with the ID
command. It is only read during that probe — nothing arrives from it
unsolicited — so it has neither a reader nor a watchdog, and its
PicoConnection leaves those fields unset.
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

# The UI Pico's reply to PING. Consumed by the watchdog, never delivered to a
# send_ui_command caller.
_PONG_LINE = "=== OK: PONG"


@dataclass
class PicoConnection:
    """State for a single serial connection to a Pico."""

    port: serial.Serial
    device: str
    reader_thread: threading.Thread | None = None
    watchdog_thread: threading.Thread | None = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    # Serializes writes to the port. The watchdog and send_ui_command both
    # write, and a split write would corrupt both lines.
    write_lock: threading.Lock = field(default_factory=threading.Lock)
    # Monotonic timestamp of the last byte received. Written only by the reader
    # thread, read only by the watchdog, and always assigned as a whole value —
    # never incremented. A second writer or a read-modify-write would need a
    # lock.
    last_rx_monotonic: float = field(default_factory=time.monotonic)
    # Monotonic timestamp of the last PONG. Written only by the reader, read
    # only by the watchdog, whole-value. The count of unanswered pings is a
    # local in the watchdog loop: a shared counter would need a lock, because
    # "+= 1" is a read-modify-write and could drop the reader's reset.
    last_pong_monotonic: float = 0.0


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
        # Take the slots first so a reader tearing down concurrently finds them
        # empty and stays quiet, then join outside the lock — _teardown_ui
        # acquires the same lock, so joining while holding it would deadlock.
        with self._lock:
            conns = [self._ui_pico, self._halspa_pico]
            self._ui_pico = None
            self._halspa_pico = None
        for conn in conns:
            if conn is not None:
                conn.stop_event.set()
        if self._reconnect_thread:
            self._reconnect_thread.join(timeout=3)
        for conn in conns:
            if conn is not None:
                self._close_pico(conn)

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
            with pico.write_lock:
                pico.port.write(f"{cmd}\n".encode())
                pico.port.flush()
        except (serial.SerialException, OSError, TypeError):
            # TypeError: the watchdog closed the port (fd set to None) between
            # the is_open check and the write.
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

        # _discover runs on one thread at a time: start() calls it before the
        # reconnect thread exists, and afterwards only that thread calls it. The
        # connect helpers publish into the slot themselves, so no placeholder is
        # needed — and a non-PicoConnection placeholder would crash every reader
        # of the slot, send_ui_command included.
        for port_info in pico_ports:
            if port_info.serial_number == _UI_PICO_SERIAL:
                if self._ui_pico is None:
                    self._connect_ui_pico(port_info)
            elif self._halspa_pico is None:
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
            # write_timeout matters as much as the read timeout here: a device
            # that stops draining its CDC OUT endpoint makes an untimed write
            # block forever, which would park the watchdog in the very stall it
            # exists to detect.
            ser = serial.Serial(
                port_info.device, 115200,
                timeout=config.SERIAL_TIMEOUT,
                write_timeout=config.SERIAL_WRITE_TIMEOUT,
            )
            ser.reset_input_buffer()
        except serial.SerialException:
            logger.warning("Failed to open UI Pico at %s", port_info.device)
            return

        conn = PicoConnection(port=ser, device=port_info.device)
        # Publish the connection before starting the threads. Teardown only
        # clears the slot when it still holds this connection, so a thread that
        # fails before the slot is published could otherwise leave a dead
        # connection installed that nothing ever reconnects.
        #
        # Refuse to publish once shutdown has begun: stop() has already taken
        # its snapshot of the slots, so anything installed afterwards would keep
        # its threads and its port alive past teardown.
        with self._lock:
            if self._stop_event.is_set():
                try:
                    ser.close()
                except (serial.SerialException, OSError):
                    pass
                return
            self._ui_pico = conn
        conn.reader_thread = threading.Thread(
            target=self._ui_reader_loop, args=(conn,),
            daemon=True, name="ui-pico-reader",
        )
        conn.reader_thread.start()
        conn.watchdog_thread = threading.Thread(
            target=self._ui_watchdog_loop, args=(conn,),
            daemon=True, name="ui-pico-watchdog",
        )
        conn.watchdog_thread.start()
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
                    conn = PicoConnection(port=ser, device=port_info.device)
                    with self._lock:
                        # Same shutdown guard as the UI side: stop() has
                        # already snapshotted the slots.
                        if self._stop_event.is_set():
                            ser.close()
                            return
                        self._sandwich_type = sandwich_id
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

    def _teardown_ui(self, conn: PicoConnection) -> None:
        """Close a UI connection and release its slot. Safe from any thread.

        Whoever notices the failure calls this — the reader on an exception, the
        watchdog on an unanswered-ping stall. Recovery must not depend on the
        reader waking up, because a stalled link is exactly when it might not.
        The disconnect event is emitted only by the caller that still owned the
        slot, so a connection already retired by stop() stays silent.
        """
        conn.stop_event.set()
        try:
            conn.port.cancel_read()
        except (serial.SerialException, OSError, AttributeError, NotImplementedError):
            pass
        try:
            conn.port.close()
        except (serial.SerialException, OSError):
            pass
        with self._lock:
            owned = self._ui_pico is conn
            if owned:
                self._ui_pico = None
        if owned:
            self._put_event({"type": "ui_pico_disconnected"})

    def _ui_reader_loop(self, conn: PicoConnection) -> None:
        """Read lines from UI Pico, demux events vs command responses."""
        while not conn.stop_event.is_set():
            try:
                raw = conn.port.readline()
            except (serial.SerialException, OSError, TypeError):
                # TypeError arises if the port is closed (fd set to None) while
                # readline is mid-os.read — shows up on shutdown.
                if conn.stop_event.is_set():
                    return
                logger.warning("UI Pico disconnected")
                self._teardown_ui(conn)
                return

            if not raw:
                continue
            conn.last_rx_monotonic = time.monotonic()
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            if line.startswith("=== EVENT: "):
                event_name = line.removeprefix("=== EVENT: ").strip()
                self._put_event({"type": "button", "event": event_name})
            elif line == _PONG_LINE:
                # The watchdog's own traffic. Keeping it out of the response
                # slot stops it from satisfying an unrelated send_ui_command,
                # and stops the slot growing without bound while idle.
                conn.last_pong_monotonic = time.monotonic()
            elif line.startswith("=== OK:") or line.startswith("=== ERROR:"):
                self._ui_response_lines.append(line)
                self._ui_response.set()
            elif line.startswith("=== INFO:"):
                logger.debug("UI Pico info: %s", line)

    def _ui_watchdog_loop(self, conn: PicoConnection) -> None:
        """Detect CDC stalls by pinging an idle link and counting silent replies.

        A stalled USB CDC pipe stays open and delivers nothing, so the reader
        never raises and the connection looks healthy forever. After
        HEARTBEAT_INTERVAL of silence this sends PING; the reader zeroes the
        counter when the PONG arrives. Once HEARTBEAT_MAX_MISSED pings in a row
        go unanswered the link is torn down and the reconnect loop reattaches.
        Counting unanswered pings rather than elapsed silence means a single
        lost reply cannot force a reconnect on its own.
        """
        interval = config.UI_PICO_HEARTBEAT_INTERVAL
        max_missed = config.UI_PICO_HEARTBEAT_MAX_MISSED
        unanswered = 0
        last_ping_at = 0.0
        while not conn.stop_event.wait(timeout=interval):
            now = time.monotonic()
            # A PONG stamped after our last ping clears the outstanding count.
            # Checked here rather than reset by the reader so that the count
            # stays local to this thread.
            if unanswered and conn.last_pong_monotonic >= last_ping_at:
                unanswered = 0
            since_rx = now - conn.last_rx_monotonic
            if since_rx < interval:
                unanswered = 0
                continue
            if unanswered >= max_missed:
                logger.warning(
                    "UI Pico CDC stall: %d pings unanswered, no data for %.1fs, "
                    "forcing reconnect",
                    unanswered, since_rx,
                )
                self._teardown_ui(conn)
                return
            try:
                with conn.write_lock:
                    conn.port.write(b"PING\n")
                    conn.port.flush()
            except (serial.SerialException, OSError, TypeError):
                # Includes SerialTimeoutException: the device has stopped
                # draining the port, which is a stall in its own right.
                logger.warning(
                    "UI Pico write failed, forcing reconnect: %s", conn.device,
                )
                self._teardown_ui(conn)
                return
            last_ping_at = time.monotonic()
            unanswered += 1

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
            conn.port.cancel_read()
        except (serial.SerialException, OSError, AttributeError, NotImplementedError):
            pass
        try:
            conn.port.close()
        except (serial.SerialException, OSError):
            pass
        if conn.reader_thread:
            conn.reader_thread.join(timeout=2)
        if conn.watchdog_thread:
            conn.watchdog_thread.join(timeout=2)
