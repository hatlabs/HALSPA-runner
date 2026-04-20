# HALSPA Runner

Touchscreen test runner for HALSPA hardware production test jigs.

## Overview

HALSPA Runner provides a web-based operator interface for running pytest hardware tests on Raspberry Pi test stations. A FastAPI backend orchestrates test discovery and execution, streams results over WebSocket to a Lit frontend displayed in Chromium kiosk mode, and communicates with Pico microcontrollers over USB serial for physical controls (button, LEDs, buzzer) and e-stop safety.

For architecture details, API reference, and configuration, see [CLAUDE.md](CLAUDE.md).

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Node.js 18+ and npm
- For deployment: Raspberry Pi with a touchscreen, running a desktop session

## Development Setup

```bash
./run install          # Install Python + frontend dependencies
./run dev              # Start backend at http://localhost:8080
./run frontend-dev     # Start Vite dev server (separate terminal)
./run test             # Run unit tests
```

The Vite dev server proxies API and WebSocket requests to the backend and provides hot reload for frontend changes.

## Deploying to the Pi

```bash
./run frontend-build   # Build frontend into frontend/dist/
./run deploy           # Run deploy/install.sh on the Pi
```

This installs a systemd user service for the backend and a Chromium kiosk autostart entry. The backend serves the built frontend from `frontend/dist/`. Chromium opens automatically on the next login, or launch manually:

```bash
chromium-browser --kiosk http://localhost:8080
```

## Project Structure

```
src/halspa_runner/     Backend (FastAPI, serial, state machine, test orchestration)
frontend/src/          Frontend (Lit web components, WebSocket client, screens)
deploy/                systemd service, Chromium kiosk autostart, install script
tests/                 pytest unit tests
run                    Task runner (install, test, dev, deploy, etc.)
CLAUDE.md              Architecture, API reference, configuration
```

## License

MIT
