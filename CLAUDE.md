# HALSPA Runner

Touchscreen test runner for HALSPA hardware test jigs. FastAPI backend + Lit frontend served in Chromium kiosk mode on Raspberry Pi.

## Quick Start

```bash
./run install          # Install all dependencies
./run test             # Run unit tests
./run dev              # Start backend dev server
./run frontend-dev     # Start frontend dev server (separate terminal)
./run deploy           # Install on Pi with systemd + kiosk
```

## Architecture

### Backend (`src/halspa_runner/`)

- `app.py` — FastAPI app with WebSocket endpoint and REST API
- `config.py` — Environment-variable-driven configuration
- `serial_manager.py` — USB CDC communication with UI Pico and HALSPA Pico
- `test_discovery.py` — Scans `*-tests` directories for DUTs and test categories
- `test_runner.py` — pytest subprocess orchestration with output streaming
- `state.py` — Application state machine with e-stop and I2C power control

### Frontend (`frontend/src/`)

- `app-shell.js` — Top-level Lit element with WebSocket client and screen routing
- `ws-client.js` — WebSocket connection with auto-reconnect
- `screens/main-menu.js` — DUT selection with sandwich detection
- `screens/test-selection.js` — Test category picker
- `screens/test-runner-screen.js` — Live test output with progress counters
- `screens/results-summary.js` — Pass/fail summary
- `screens/estop-screen.js` — E-stop overlay

### Deployment (`deploy/`)

- `halspa-runner.service` — systemd user service for the backend
- `chromium-kiosk.desktop` — XDG autostart for Chromium kiosk mode
- `install.sh` — Installation script for Pi setup

## Configuration

All settings via environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `HALSPA_RUNNER_TEST_DIR` | `~/halspa-runner-duts` | Directory to scan for `*-tests` repos (use symlinks) |
| `HALSPA_RUNNER_PORT` | `8080` | FastAPI server port |
| `HALSPA_RUNNER_SERIAL_TIMEOUT` | `2.0` | Serial command timeout (seconds) |
| `HALSPA_RUNNER_PYTEST_TIMEOUT` | `60.0` | pytest unresponsive timeout (seconds) |

## API

### REST

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/status` | Current system state |
| GET | `/api/duts` | Discovered DUTs with categories |
| POST | `/api/start` | Start test run (body: `{dut, categories?}`) |
| POST | `/api/stop` | Cancel running test |
| POST | `/api/estop` | Remote e-stop |
| POST | `/api/clear-estop` | Clear e-stop state |
| POST | `/api/dismiss` | Dismiss results, return to idle |
| POST | `/api/shutdown` | System power off |

### WebSocket (`/ws`)

Bidirectional JSON messages. Server sends: `state_change`, `test_output`, `test_progress`, `test_complete`. Client sends: `start`, `stop`, `estop`, `clear_estop`, `dismiss`.
