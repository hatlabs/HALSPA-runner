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

def _float_env(name: str, default: str, minimum: float) -> float:
    """Read a float setting, clamped so a bad value cannot disable a timer."""
    try:
        value = float(os.environ.get(name, default))
    except ValueError:
        return float(default)
    return max(value, minimum)


def _int_env(name: str, default: str, minimum: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError:
        return int(default)
    return max(value, minimum)


# Serial communication timeouts (seconds)
SERIAL_TIMEOUT: float = _float_env("HALSPA_RUNNER_SERIAL_TIMEOUT", "2.0", 0.1)
SERIAL_WRITE_TIMEOUT: float = _float_env(
    "HALSPA_RUNNER_SERIAL_WRITE_TIMEOUT", "1.0", 0.1
)
SERIAL_RECONNECT_INTERVAL: float = _float_env(
    "HALSPA_RUNNER_SERIAL_RECONNECT_INTERVAL", "5.0", 0.1
)

# UI Pico CDC liveness watchdog. After HEARTBEAT_INTERVAL seconds of silence we
# send a PING; the device answers "=== OK: PONG". Once HEARTBEAT_MAX_MISSED
# consecutive pings go unanswered the link is treated as stalled and force
# reconnected. Counting unanswered pings rather than elapsed silence means one
# lost reply cannot trigger a reconnect on its own.
UI_PICO_HEARTBEAT_INTERVAL: float = _float_env(
    "HALSPA_RUNNER_UI_PICO_HEARTBEAT_INTERVAL", "5.0", 0.05
)
UI_PICO_HEARTBEAT_MAX_MISSED: int = _int_env(
    "HALSPA_RUNNER_UI_PICO_HEARTBEAT_MAX_MISSED", "2", 1
)

# pytest unresponsive timeout (seconds)
PYTEST_TIMEOUT: float = float(os.environ.get("HALSPA_RUNNER_PYTEST_TIMEOUT", "60.0"))
