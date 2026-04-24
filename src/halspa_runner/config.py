"""Configuration for the HALSPA runner, driven by environment variables."""

import os
from pathlib import Path


# Directory to scan for *-tests repositories
TEST_DIR: Path = Path(os.environ.get(
    "HALSPA_RUNNER_TEST_DIR",
    os.path.expanduser("~/halspa-runner-duts"),
))

# FastAPI server port
PORT: int = int(os.environ.get("HALSPA_RUNNER_PORT", "8080"))

# Serial communication timeouts (seconds)
SERIAL_TIMEOUT: float = float(os.environ.get("HALSPA_RUNNER_SERIAL_TIMEOUT", "2.0"))
SERIAL_RECONNECT_INTERVAL: float = float(os.environ.get(
    "HALSPA_RUNNER_SERIAL_RECONNECT_INTERVAL", "5.0"
))

# UI Pico CDC liveness watchdog. We send a PING if no bytes have arrived for
# HEARTBEAT_INTERVAL seconds, and force-reconnect if the silence exceeds
# HEARTBEAT_INTERVAL * STALL_FACTOR — catches USB CDC stalls where the port
# stays open but the pipe stops delivering bytes.
UI_PICO_HEARTBEAT_INTERVAL: float = float(os.environ.get(
    "HALSPA_RUNNER_UI_PICO_HEARTBEAT_INTERVAL", "5.0"
))
UI_PICO_HEARTBEAT_STALL_FACTOR: float = float(os.environ.get(
    "HALSPA_RUNNER_UI_PICO_HEARTBEAT_STALL_FACTOR", "3.0"
))

# pytest unresponsive timeout (seconds)
PYTEST_TIMEOUT: float = float(os.environ.get("HALSPA_RUNNER_PYTEST_TIMEOUT", "60.0"))
