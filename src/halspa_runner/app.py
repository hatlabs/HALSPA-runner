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
from .test_discovery import discover_duts
from .test_runner import PytestRunner, RunStatus

logger = logging.getLogger(__name__)

# Global instances (initialized in lifespan)
serial_manager: SerialManager | None = None
state_machine: StateMachine | None = None
test_runner: PytestRunner | None = None


class StartRequest(BaseModel):
    dut: str
    categories: list[str] | None = None


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


async def _handle_button(event_name: str) -> None:
    assert state_machine is not None

    if event_name == "BUTTON_ESTOP":
        state_machine.handle_estop()
        return

    if event_name == "BUTTON_START":
        state = state_machine.state
        if state == AppState.IDLE and serial_manager and serial_manager.sandwich_type:
            # Start "Run All" for detected DUT
            dut_name = serial_manager.sandwich_type
            duts = discover_duts()
            matching = [d for d in duts if d.name == dut_name]
            if matching:
                await _start_test_run(dut_name, None, matching[0].path)
        elif state == AppState.RESULTS_PASS or state == AppState.RESULTS_FAIL:
            state_machine.dismiss_results()


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


@app.post("/api/start")
async def start_tests(req: StartRequest) -> JSONResponse:
    assert state_machine is not None

    if state_machine.state == AppState.RUNNING:
        return JSONResponse({"error": "Tests already running"}, status_code=409)

    duts = discover_duts()
    matching = [d for d in duts if d.name == req.dut]
    if not matching:
        return JSONResponse({"error": f"DUT '{req.dut}' not found"}, status_code=404)

    asyncio.create_task(
        _start_test_run(req.dut, req.categories, matching[0].path)
    )
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
    })

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")

            if msg_type == "start":
                dut = data.get("dut")
                categories = data.get("categories")
                duts = discover_duts()
                matching = [d for d in duts if d.name == dut]
                if matching:
                    asyncio.create_task(
                        _start_test_run(dut, categories, matching[0].path)
                    )
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


async def _start_test_run(
    dut_name: str,
    categories: list[str] | None,
    repo_path: Path,
) -> None:
    """Start a test run and stream results."""
    assert state_machine is not None
    assert test_runner is not None

    state_machine.select_dut(dut_name)
    state_machine.start_running()

    async def on_line(line: str) -> None:
        await ws_manager.broadcast({"type": "test_output", "line": line})

    async def on_progress(progress: Any) -> None:
        await ws_manager.broadcast({
            "type": "test_progress",
            "passed": progress.passed,
            "failed": progress.failed,
            "skipped": progress.skipped,
            "errors": progress.errors,
            "current_test": progress.current_test,
            "elapsed": round(progress.elapsed, 1),
        })

    result = await test_runner.run(
        repo_path, categories=categories,
        on_line=on_line, on_progress=on_progress,
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
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True))
