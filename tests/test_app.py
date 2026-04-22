"""Tests for the FastAPI app endpoints."""

from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from halspa_runner import app as app_module
from halspa_runner.app import app
from halspa_runner.state import AppState, StateMachine
from halspa_runner.test_discovery import Category, DUT, discover_duts


@pytest.fixture
def mock_state() -> StateMachine:
    sm = StateMachine()
    sm.set_ready()
    return sm


@pytest.fixture
def mock_serial() -> MagicMock:
    m = MagicMock()
    m.sandwich_type = "HALPI2"
    m.sandwich_detection_complete = True
    m.ui_pico_connected = True
    m.halspa_pico_connected = True
    return m


@pytest.fixture
def mock_runner() -> MagicMock:
    m = MagicMock()
    m.is_running = False
    m.cancel = AsyncMock()
    return m


@pytest.fixture
def client(mock_state: StateMachine, mock_serial: MagicMock, mock_runner: MagicMock):
    # Set globals directly, bypassing lifespan
    app_module.state_machine = mock_state
    app_module.serial_manager = mock_serial
    app_module.test_runner = mock_runner

    # Replace lifespan with a no-op
    @asynccontextmanager
    async def noop_lifespan(app):
        yield

    original_router_lifespan = app.router.lifespan_context
    app.router.lifespan_context = noop_lifespan

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    # Restore
    app.router.lifespan_context = original_router_lifespan
    app_module.state_machine = None
    app_module.serial_manager = None
    app_module.test_runner = None


def test_get_status(client: TestClient, mock_state: StateMachine) -> None:
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "idle"
    assert data["sandwich_type"] == "HALPI2"
    assert data["selected_dut"] is None
    assert data["ui_pico_connected"] is True


def test_get_status_with_selected_dut(
    client: TestClient, mock_state: StateMachine,
) -> None:
    mock_state.select_dut("HALPI2")
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["selected_dut"] == "HALPI2"


def test_get_duts(client: TestClient) -> None:
    mock_duts = [
        DUT(
            name="HALPI2",
            path="/tmp/HALPI2-tests",
            categories=[Category(name="000_selftest", path="/tmp/tests/000")],
        ),
    ]
    with patch("halspa_runner.app.discover_duts", return_value=mock_duts):
        resp = client.get("/api/duts")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "HALPI2"
    assert data[0]["categories"][0]["name"] == "000_selftest"


def test_start_while_running(client: TestClient, mock_state: StateMachine) -> None:
    mock_state.transition(AppState.RUNNING)

    resp = client.post("/api/start", json={"dut": "HALPI2"})
    assert resp.status_code == 409


def test_start_unknown_dut(client: TestClient) -> None:
    with patch("halspa_runner.app.discover_duts", return_value=[]):
        resp = client.post("/api/start", json={"dut": "NONEXISTENT"})
    assert resp.status_code == 404


def test_estop_endpoint(client: TestClient, mock_state: StateMachine) -> None:
    resp = client.post("/api/estop")
    assert resp.status_code == 200
    assert mock_state.state == AppState.ESTOP


def test_clear_estop_endpoint(client: TestClient, mock_state: StateMachine) -> None:
    mock_state.handle_estop()
    resp = client.post("/api/clear-estop")
    assert resp.status_code == 200
    assert mock_state.state == AppState.IDLE


def test_dismiss_results(client: TestClient, mock_state: StateMachine) -> None:
    mock_state.transition(AppState.RESULTS_PASS)
    resp = client.post("/api/dismiss")
    assert resp.status_code == 200
    assert mock_state.state == AppState.DUT_SELECTED


def test_browse_root(client: TestClient, tmp_path: Path) -> None:
    # Create a DUT with test directories on the filesystem
    repo = tmp_path / "HALPI2-tests"
    tests_dir = repo / "tests"
    power_dir = tests_dir / "100_power"
    power_dir.mkdir(parents=True)
    (power_dir / "test_rails.py").touch()

    mock_dut = DUT(name="HALPI2", path=repo, categories=[Category(name="100_power", path=power_dir)])

    with patch("halspa_runner.app.discover_duts", return_value=[mock_dut]):
        resp = client.get("/api/duts/HALPI2/browse")

    assert resp.status_code == 200
    data = resp.json()
    assert data["breadcrumbs"] == []
    assert len(data["entries"]) >= 1
    names = [e["name"] for e in data["entries"]]
    assert "100_power" in names


def test_browse_dut_not_found(client: TestClient) -> None:
    with patch("halspa_runner.app.discover_duts", return_value=[]):
        resp = client.get("/api/duts/NONEXISTENT/browse")

    assert resp.status_code == 404


def test_browse_invalid_path(client: TestClient, tmp_path: Path) -> None:
    repo = tmp_path / "HALPI2-tests"
    tests_dir = repo / "tests"
    tests_dir.mkdir(parents=True)

    mock_dut = DUT(name="HALPI2", path=repo, categories=[])

    with patch("halspa_runner.app.discover_duts", return_value=[mock_dut]):
        resp = client.get("/api/duts/HALPI2/browse", params={"path": "../../etc"})

    assert resp.status_code == 400


def test_websocket_initial_message_includes_sandwich_type(
    client: TestClient, mock_serial: MagicMock,
) -> None:
    with client.websocket_connect("/ws") as ws:
        data = ws.receive_json()
        assert data["type"] == "state_change"
        assert data["sandwich_type"] == "HALPI2"
        assert data["sandwich_detection_complete"] is True


def test_websocket_initial_message_sandwich_type_none(
    client: TestClient, mock_serial: MagicMock,
) -> None:
    mock_serial.sandwich_type = None
    with client.websocket_connect("/ws") as ws:
        data = ws.receive_json()
        assert data["sandwich_type"] is None
        assert data["sandwich_detection_complete"] is True


def test_websocket_initial_message_sandwich_detection_pending(
    client: TestClient, mock_serial: MagicMock,
) -> None:
    mock_serial.sandwich_type = None
    mock_serial.sandwich_detection_complete = False
    with client.websocket_connect("/ws") as ws:
        data = ws.receive_json()
        assert data["sandwich_type"] is None
        assert data["sandwich_detection_complete"] is False


def test_websocket_initial_message_includes_selected_dut(
    client: TestClient, mock_state: StateMachine,
) -> None:
    with client.websocket_connect("/ws") as ws:
        data = ws.receive_json()
        assert data["type"] == "state_change"
        assert data["selected_dut"] is None


def test_websocket_initial_message_selected_dut_after_selection(
    client: TestClient, mock_state: StateMachine,
) -> None:
    mock_state.select_dut("HALPI2")
    with client.websocket_connect("/ws") as ws:
        data = ws.receive_json()
        assert data["selected_dut"] == "HALPI2"
