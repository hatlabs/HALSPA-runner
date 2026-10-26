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
- `screens/estop-modal.js` — E-stop overlay

### Deployment (`deploy/`)

- `halspa-runner.service` — systemd user service for the backend
- `chromium-kiosk.desktop` — XDG autostart for Chromium kiosk mode
- `install.sh` — Installation script for Pi setup

### Documented Solutions (`docs/solutions/`)

Past problem solutions and best practices, organized by category with YAML frontmatter (`module`, `tags`, `problem_type`). Relevant when implementing or debugging in documented areas.

## Configuration

All settings via environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `HALSPA_RUNNER_TEST_DIR` | `~/halspa-runner-duts` | Directory to scan for `*-tests` repos (use symlinks) |
| `HALSPA_RUNNER_PORT` | `8080` | FastAPI server port |
| `HALSPA_RUNNER_SERIAL_TIMEOUT` | `2.0` | Serial read and command timeout (seconds) |
| `HALSPA_RUNNER_SERIAL_WRITE_TIMEOUT` | `1.0` | Serial write timeout (seconds); bounds a write to a device that has stopped draining its port |
| `HALSPA_RUNNER_SERIAL_RECONNECT_INTERVAL` | `5.0` | How often to rescan for missing Picos (seconds) |
| `HALSPA_RUNNER_UI_PICO_HEARTBEAT_INTERVAL` | `2.5` | Idle time before the UI Pico watchdog sends a PING (seconds) |
| `HALSPA_RUNNER_UI_PICO_HEARTBEAT_MAX_MISSED` | `2` | Consecutive unanswered pings before the UI Pico link is force-reconnected |
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

Bidirectional JSON messages. Server sends: `state_change`, `test_output`, `test_progress`, `test_complete`, `retry_refused`. Client sends: `start`, `stop`, `estop`, `clear_estop`, `dismiss`, `retry_failed`.

`test_complete` carries `failed_tests`, the node IDs that failed or errored (a teardown failure counts as an error). It is non-empty only after a run with status `failed` in which every collected test reported a result, so a passing retry means the whole selection passed. `retry_failed` reruns exactly those, from `results_fail` only, without changing the selected targets: Done and the START button still run the original selection. A `retry_failed` that cannot run is answered with `retry_refused`.

## Rendering the UI

The frontend renders without the backend or the jig. Serve it and drive its states by injecting server messages:

```bash
./run install
cd frontend && npx vite --port 5199
```

Open `http://localhost:5199/` at 1280x720 (the kiosk panel in landscape). The WebSocket and `/api/duts` console errors are expected with no backend. In the browser console:

```js
const shell = document.querySelector("app-shell");
window.removeEventListener("ws-disconnected", shell._boundOnDisconnected);
shell.connected = true;  // Retry is disabled while the socket is down; drop this for the "Disconnected" badge
const send = (d) => shell._onMessage({ detail: d });
const sc = (state, old_state) => send({ type: "state_change", state, old_state, selected_dut: "HALPI2", ui_pico_connected: true });
sc("dut_selected", "idle");
sc("running", "dut_selected");   // running view
send({ type: "test_progress", passed: 11, failed: 1, skipped: 1, errors: 1, total: 14, current_test: "", elapsed: 42 });
sc("results_fail", "running");
send({ type: "test_complete", status: "failed", passed: 11, failed: 1, skipped: 1, errors: 1, elapsed: 42,
       failed_tests: ["tests/a_test.py::test_a", "tests/b_test.py::test_b"] });  // FAIL with "Retry failed (2)"
```

Other states from there:

- Not retryable (cancelled, timeout, e-stop): `test_complete` with `failed_tests: []`.
- Retry pending: press "Retry failed" (with no backend the send fails and the button resets; to keep it pending, first run `(await import("/src/ws-client.js")).wsClient.send = () => true`). Refused for the link: `send({ type: "start_refused", reason: "ui_pico_disconnected" })`; link back: `send({ type: "ui_pico_connected" })`. Refused as stale: `send({ type: "retry_refused" })`.
- Retry started: `sc("running", "results_fail")`. Passed: `sc("results_pass", "running")` and `test_complete` with `status: "passed"`.
- E-stop modal: `sc("estop", "running")`.
