"""FastAPI application wiring together all backend modules."""

import asyncio
import logging
import os
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .serial_manager import SerialManager
from .state import AppState, StateMachine
from .test_discovery import browse_test_path, discover_duts
from .test_runner import PytestRunner, RunStatus

logger = logging.getLogger(__name__)

# Global instances (initialized in lifespan)
serial_manager: SerialManager | None = None
state_machine: StateMachine | None = None
test_runner: PytestRunner | None = None


class StartRequest(BaseModel):
    dut: str
    categories: list[str] | None = None
    targets: list[str] | None = None


class ConnectionManager:
    """Track active WebSocket connections and broadcast messages."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.remove(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.remove(ws)


ws_manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global serial_manager, state_machine, test_runner

    logging.basicConfig(level=logging.INFO)

    loop = asyncio.get_event_loop()
    serial_manager = SerialManager(loop=loop)
    test_runner = PytestRunner()
    state_machine = StateMachine(
        serial_manager=serial_manager, test_runner=test_runner,
    )

    # State change callback: broadcast to all WebSocket clients
    def on_state_change(old: AppState, new: AppState) -> None:
        msg = {
            "type": "state_change",
            "state": new.value,
            "old_state": old.value,
            "sandwich_type": serial_manager.sandwich_type if serial_manager else None,
            "selected_dut": state_machine.selected_dut if state_machine else None,
        }
        if new == AppState.ESTOP and state_machine:
            msg["power_off_failed"] = state_machine.estop_power_off_failed
        asyncio.run_coroutine_threadsafe(ws_manager.broadcast(msg), loop)

    state_machine.on_state_change(on_state_change)

    # Start serial manager
    serial_manager.start()

    # Start event consumer
    event_task = asyncio.create_task(_consume_events())

    # Mark ready
    state_machine.set_ready()

    yield

    # Cleanup
    event_task.cancel()
    serial_manager.stop()


async def _consume_events() -> None:
    """Consume events from serial manager and dispatch them."""
    while True:
        assert serial_manager is not None
        event = await serial_manager.get_event()
        logger.info("Event: %s", event)

        if event.get("type") == "button":
            await _handle_button(event["event"])
        elif event.get("type") == "ui_pico_disconnected":
            await ws_manager.broadcast({"type": "ui_pico_disconnected"})
        elif event.get("type") == "sandwich_detected":
            await ws_manager.broadcast({
                "type": "state_change",
                "state": state_machine.state.value,
                "old_state": state_machine.state.value,
                "sandwich_type": event["sandwich_type"],
                "selected_dut": state_machine.selected_dut if state_machine else None,
            })


async def _handle_button(event_name: str) -> None:
    assert state_machine is not None

    if event_name == "BUTTON_ESTOP":
        state_machine.handle_estop()
        return

    if event_name == "BUTTON_START":
        state = state_machine.state

        if state in (AppState.RESULTS_PASS, AppState.RESULTS_FAIL):
            # Dismiss results (→ DUT_SELECTED) and fall through to start
            state_machine.dismiss_results()
            state = state_machine.state

        if state == AppState.DUT_SELECTED:
            # Re-run with stored DUT + targets
            await _start_test_run()
        elif state == AppState.IDLE and serial_manager and serial_manager.sandwich_type:
            # Auto-select DUT from sandwich, run all
            dut_name = serial_manager.sandwich_type
            duts = discover_duts()
            matching = [d for d in duts if d.name == dut_name]
            if matching:
                state_machine.select_dut(dut_name, matching[0].path)
                await _start_test_run()
            else:
                logger.warning("Button press: no DUT matching sandwich type '%s'", dut_name)
        elif state == AppState.IDLE:
            logger.warning("Button press ignored: no sandwich type detected")


app = FastAPI(lifespan=lifespan)


@app.get("/api/status")
async def get_status() -> dict[str, Any]:
    assert state_machine is not None
    return {
        "state": state_machine.state.value,
        "selected_dut": state_machine.selected_dut,
        "sandwich_type": serial_manager.sandwich_type if serial_manager else None,
        "ui_pico_connected": serial_manager.ui_pico_connected if serial_manager else False,
        "halspa_pico_connected": serial_manager.halspa_pico_connected if serial_manager else False,
    }


@app.get("/api/duts")
async def get_duts() -> list[dict[str, Any]]:
    duts = discover_duts()
    return [
        {
            "name": dut.name,
            "categories": [{"name": c.name} for c in dut.categories],
        }
        for dut in duts
    ]


@app.get("/api/duts/{dut_name}/browse")
async def browse_dut(dut_name: str, path: str = "") -> JSONResponse:
    duts = discover_duts()
    matching = [d for d in duts if d.name == dut_name]
    if not matching:
        return JSONResponse({"error": f"DUT '{dut_name}' not found"}, status_code=404)

    try:
        entries = await browse_test_path(matching[0].path, path)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except OSError as e:
        logger.warning("Browse failed for %s path=%s: %s", dut_name, path, e)
        return JSONResponse({"error": "Could not browse path"}, status_code=500)

    # Build breadcrumbs from the path
    breadcrumbs: list[dict[str, str]] = []
    if path:
        parts = path.split("/")
        for i, part in enumerate(parts):
            breadcrumbs.append({
                "name": part,
                "path": "/".join(parts[: i + 1]),
            })

    return JSONResponse({
        "entries": [{"name": e.name, "type": e.type, "path": e.path} for e in entries],
        "breadcrumbs": breadcrumbs,
    })


@app.post("/api/start")
async def start_tests(req: StartRequest) -> JSONResponse:
    assert state_machine is not None

    if state_machine.state == AppState.RUNNING:
        return JSONResponse({"error": "Tests already running"}, status_code=409)

    duts = discover_duts()
    matching = [d for d in duts if d.name == req.dut]
    if not matching:
        return JSONResponse({"error": f"DUT '{req.dut}' not found"}, status_code=404)

    state_machine.select_dut(req.dut, matching[0].path)
    targets = req.targets or req.categories
    if targets:
        state_machine.set_targets(targets)

    asyncio.create_task(_start_test_run())
    return JSONResponse({"status": "started"})


@app.post("/api/stop")
async def stop_tests() -> JSONResponse:
    assert test_runner is not None
    if test_runner.is_running:
        await test_runner.cancel()
    return JSONResponse({"status": "stopped"})


@app.post("/api/estop")
async def estop() -> JSONResponse:
    assert state_machine is not None
    state_machine.handle_estop()
    return JSONResponse({"status": "estop_activated"})


@app.post("/api/clear-estop")
async def clear_estop() -> JSONResponse:
    assert state_machine is not None
    state_machine.clear_estop()
    return JSONResponse({"status": "cleared"})


@app.post("/api/dismiss")
async def dismiss_results() -> JSONResponse:
    assert state_machine is not None
    state_machine.dismiss_results()
    return JSONResponse({"status": "dismissed"})


@app.post("/api/shutdown")
async def shutdown() -> JSONResponse:
    subprocess.Popen(["systemctl", "poweroff"])
    return JSONResponse({"status": "shutting_down"})


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws_manager.connect(ws)
    assert state_machine is not None

    # Send initial state
    await ws.send_json({
        "type": "state_change",
        "state": state_machine.state.value,
        "old_state": None,
        "sandwich_type": serial_manager.sandwich_type if serial_manager else None,
        "selected_dut": state_machine.selected_dut if state_machine else None,
    })

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")

            if msg_type == "select_dut":
                dut = data.get("dut")
                duts = discover_duts()
                matching = [d for d in duts if d.name == dut]
                if matching:
                    state_machine.select_dut(dut, matching[0].path)
            elif msg_type == "select":
                targets = data.get("targets")
                state_machine.set_targets(targets)
            elif msg_type == "deselect":
                state_machine.deselect_dut()
            elif msg_type == "start":
                dut = data.get("dut")
                targets = data.get("targets")
                # If DUT not yet selected in state machine, select it now
                if state_machine.selected_dut != dut:
                    duts = discover_duts()
                    matching = [d for d in duts if d.name == dut]
                    if matching:
                        state_machine.select_dut(dut, matching[0].path)
                    else:
                        continue
                if targets is not None:
                    state_machine.set_targets(targets)
                asyncio.create_task(_start_test_run())
            elif msg_type == "stop":
                if test_runner and test_runner.is_running:
                    await test_runner.cancel()
            elif msg_type == "estop":
                state_machine.handle_estop()
            elif msg_type == "clear_estop":
                state_machine.clear_estop()
            elif msg_type == "dismiss":
                state_machine.dismiss_results()
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)


async def _start_test_run() -> None:
    """Start a test run using DUT + targets from state machine."""
    assert state_machine is not None
    assert test_runner is not None

    repo_path = state_machine.selected_repo_path
    targets = state_machine.selected_targets

    if not repo_path:
        logger.error("Cannot start test run: no repo path in state machine")
        await ws_manager.broadcast({
            "type": "test_complete",
            "status": "error",
            "exit_code": None,
            "passed": 0, "failed": 0, "skipped": 0, "elapsed": 0,
        })
        return

    state_machine.start_running()

    async def on_line(line: str) -> None:
        await ws_manager.broadcast({"type": "test_output", "line": line})

    async def on_test_start(nodeid: str) -> None:
        await ws_manager.broadcast({"type": "test_start", "nodeid": nodeid})

    async def on_progress(progress: Any) -> None:
        await ws_manager.broadcast({
            "type": "test_progress",
            "passed": progress.passed,
            "failed": progress.failed,
            "skipped": progress.skipped,
            "errors": progress.errors,
            "total": progress.total,
            "current_test": progress.current_test,
            "elapsed": round(progress.elapsed, 1),
        })

    result = await test_runner.run(
        repo_path, targets=targets,
        on_line=on_line, on_progress=on_progress,
        on_test_start=on_test_start,
    )

    if state_machine.state == AppState.ESTOP:
        return  # E-stop already handled the state transition

    if result.status == RunStatus.PASSED:
        state_machine.tests_completed(passed=True)
    elif result.status in (RunStatus.FAILED, RunStatus.ERROR, RunStatus.TIMEOUT):
        state_machine.tests_completed(passed=False)
    elif result.status == RunStatus.CANCELLED:
        state_machine.tests_completed(passed=False)

    await ws_manager.broadcast({
        "type": "test_complete",
        "status": result.status.value,
        "exit_code": result.exit_code,
        "passed": result.progress.passed,
        "failed": result.progress.failed,
        "skipped": result.progress.skipped,
        "elapsed": round(result.progress.elapsed, 1),
    })


# Mount static files for frontend (if dist/ exists)
_frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if _frontend_dist.is_dir():
    from starlette.middleware.base import BaseHTTPMiddleware

    class NoCacheHTMLMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            response = await call_next(request)
            content_type = response.headers.get("content-type", "")
            if "text/html" in content_type:
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return response

    app.add_middleware(NoCacheHTMLMiddleware)
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True))
