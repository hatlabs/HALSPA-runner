# HALSPA Runner

Touchscreen test runner for HALSPA hardware test jigs. FastAPI backend + Lit frontend served in Chromium kiosk mode on Raspberry Pi.

## Build & Test

```bash
uv sync --extra dev    # Install dependencies
uv run pytest          # Run unit tests
```

## Architecture

- `src/halspa_runner/config.py` — Environment-variable-driven configuration
- `src/halspa_runner/test_discovery.py` — Scans `*-tests` directories for DUTs and test categories

## Configuration

All settings via environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `HALSPA_RUNNER_TEST_DIR` | `~/src/HALSPA` | Directory to scan for `*-tests` repos |
| `HALSPA_RUNNER_PORT` | `8080` | FastAPI server port |
| `HALSPA_RUNNER_SERIAL_TIMEOUT` | `2.0` | Serial command timeout (seconds) |
| `HALSPA_RUNNER_PYTEST_TIMEOUT` | `60.0` | pytest unresponsive timeout (seconds) |
