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

# pytest unresponsive timeout (seconds)
PYTEST_TIMEOUT: float = float(os.environ.get("HALSPA_RUNNER_PYTEST_TIMEOUT", "60.0"))
