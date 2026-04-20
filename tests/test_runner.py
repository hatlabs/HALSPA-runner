"""Tests for test_runner module with mock subprocesses and JSONL reports."""

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from halspa_runner.test_runner import RunStatus, PytestRunner


@pytest.fixture
def runner() -> PytestRunner:
    return PytestRunner()


def _write_report(path: str, events: list[dict]) -> None:
    """Write JSONL events to a report file."""
    with open(path, "w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")


def _setup_mock(
    lines: list[bytes],
    exit_code: int = 0,
    report_path: str | None = None,
    report_events: list[dict] | None = None,
):
    """Create mocks for PTY-based subprocess.

    Returns (process_mock, patches_context_manager).
    The context manager patches pty.openpty, create_subprocess_exec,
    and tempfile.mkstemp.
    """
    process = MagicMock()
    process.pid = 12345
    process.returncode = None

    async def wait() -> int:
        process.returncode = exit_code
        return exit_code
    process.wait = wait

    # Create a pipe pair to simulate PTY output
    read_fd, write_fd = os.pipe()

    # Write all output lines
    for line in lines:
        os.write(write_fd, line)
    os.close(write_fd)

    # Store report events to write after mkstemp (which truncates the file)
    _report_path = report_path
    _report_events = report_events

    class _Patches:
        """Context manager that applies all needed patches."""
        def __init__(self):
            self._patches = []

        def __enter__(self):
            # Patch pty.openpty to return our pipe (read_fd) and a dummy slave
            dummy_slave_r, dummy_slave_w = os.pipe()
            os.close(dummy_slave_r)

            p1 = patch("halspa_runner.test_runner.pty.openpty",
                        return_value=(read_fd, dummy_slave_w))
            p2 = patch("halspa_runner.test_runner.asyncio.create_subprocess_exec",
                        return_value=process)

            self._patches = [p1, p2]
            mocks = [p.start() for p in self._patches]

            if _report_path:
                def fake_mkstemp(**kwargs):
                    # Create an empty file, return fd for runner to close
                    fd = os.open(_report_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
                    # Write report events immediately — runner closes fd
                    # before the report reader opens the file
                    if _report_events:
                        for evt in _report_events:
                            os.write(fd, (json.dumps(evt) + "\n").encode())
                    return fd, _report_path
                p3 = patch("halspa_runner.test_runner.tempfile.mkstemp",
                           side_effect=fake_mkstemp)
                self._patches.append(p3)
                p3.start()

            self.mock_exec = mocks[1]
            return self

        def __exit__(self, *args):
            for p in self._patches:
                p.stop()

    return process, _Patches()


@pytest.mark.asyncio
async def test_successful_run(runner: PytestRunner, tmp_path: Path) -> None:
    report_path = str(tmp_path / "report.jsonl")
    report_events = [
        {"event": "collected", "total": 2},
        {"event": "result", "nodeid": "tests/test_ping.py::test_ping", "outcome": "passed"},
        {"event": "result", "nodeid": "tests/test_ping.py::test_pong", "outcome": "passed"},
    ]
    lines = [
        b"tests/test_ping.py::test_ping PASSED                           [  50%]\n",
        b"tests/test_ping.py::test_pong PASSED                           [ 100%]\n",
    ]
    _, patches = _setup_mock(lines, exit_code=0, report_path=report_path, report_events=report_events)

    with patches:
        result = await runner.run(tmp_path)

    assert result.status == RunStatus.PASSED
    assert result.progress.passed == 2
    assert result.progress.failed == 0
    assert result.progress.total == 2
    assert result.exit_code == 0


@pytest.mark.asyncio
async def test_failed_run(runner: PytestRunner, tmp_path: Path) -> None:
    report_path = str(tmp_path / "report.jsonl")
    report_events = [
        {"event": "collected", "total": 2},
        {"event": "result", "nodeid": "tests/test_5v.py::test_5v_output", "outcome": "passed"},
        {"event": "result", "nodeid": "tests/test_5v.py::test_overcurrent", "outcome": "failed"},
    ]
    lines = [
        b"tests/test_5v.py::test_5v_output PASSED                       [  50%]\n",
        b"tests/test_5v.py::test_overcurrent FAILED                      [ 100%]\n",
    ]
    _, patches = _setup_mock(lines, exit_code=1, report_path=report_path, report_events=report_events)

    with patches:
        result = await runner.run(tmp_path)

    assert result.status == RunStatus.FAILED
    assert result.progress.passed == 1
    assert result.progress.failed == 1
    assert result.progress.total == 2
    assert result.exit_code == 1


@pytest.mark.asyncio
async def test_skipped_tests(runner: PytestRunner, tmp_path: Path) -> None:
    report_path = str(tmp_path / "report.jsonl")
    report_events = [
        {"event": "collected", "total": 2},
        {"event": "result", "nodeid": "tests/test_i2c.py::test_scan", "outcome": "passed"},
        {"event": "result", "nodeid": "tests/test_i2c.py::test_optional", "outcome": "skipped"},
    ]
    lines = [
        b"tests/test_i2c.py::test_scan PASSED                           [  50%]\n",
        b"tests/test_i2c.py::test_optional SKIPPED (no hw)               [ 100%]\n",
    ]
    _, patches = _setup_mock(lines, exit_code=0, report_path=report_path, report_events=report_events)

    with patches:
        result = await runner.run(tmp_path)

    assert result.progress.passed == 1
    assert result.progress.skipped == 1
    assert result.progress.total == 2


@pytest.mark.asyncio
async def test_on_line_callback(runner: PytestRunner, tmp_path: Path) -> None:
    report_path = str(tmp_path / "report.jsonl")
    report_events = [
        {"event": "collected", "total": 1},
        {"event": "result", "nodeid": "tests/test_ping.py::test_ping", "outcome": "passed"},
    ]
    lines = [
        b"tests/test_ping.py::test_ping PASSED                          [ 100%]\n",
    ]
    _, patches = _setup_mock(lines, exit_code=0, report_path=report_path, report_events=report_events)
    received_lines: list[str] = []

    async def on_line(line: str) -> None:
        received_lines.append(line)

    with patches:
        await runner.run(tmp_path, on_line=on_line)

    assert any("test_ping PASSED" in line for line in received_lines)


@pytest.mark.asyncio
async def test_strips_ansi_codes(runner: PytestRunner, tmp_path: Path) -> None:
    report_path = str(tmp_path / "report.jsonl")
    report_events = [
        {"event": "collected", "total": 1},
        {"event": "result", "nodeid": "tests/test_ping.py::test_ping", "outcome": "passed"},
    ]
    lines = [
        b"\x1b[32mtests/test_ping.py::test_ping PASSED\x1b[0m\n",
    ]
    _, patches = _setup_mock(lines, exit_code=0, report_path=report_path, report_events=report_events)
    received_lines: list[str] = []

    async def on_line(line: str) -> None:
        received_lines.append(line)

    with patches:
        await runner.run(tmp_path, on_line=on_line)

    assert received_lines[0] == "tests/test_ping.py::test_ping PASSED"
    assert "\x1b" not in received_lines[0]


@pytest.mark.asyncio
async def test_cancel(runner: PytestRunner, tmp_path: Path) -> None:
    report_path = str(tmp_path / "report.jsonl")
    _write_report(report_path, [])

    process = MagicMock()
    process.pid = 12345
    process.returncode = None

    # Create a pipe that blocks on read (simulating a long test)
    read_fd, write_fd = os.pipe()

    # Write one line then keep pipe open
    os.write(write_fd, b"tests/test_slow.py::test_slow starting...\n")

    cancel_called = False

    def send_signal(sig: int) -> None:
        nonlocal cancel_called
        cancel_called = True
        # Close the write end to unblock the reader
        try:
            os.close(write_fd)
        except OSError:
            pass

    process.send_signal = send_signal

    async def wait() -> int:
        if cancel_called:
            process.returncode = -15
            return -15
        await asyncio.sleep(10)
        process.returncode = 0
        return 0

    process.wait = wait

    dummy_slave_r, dummy_slave_w = os.pipe()
    os.close(dummy_slave_r)

    def fake_mkstemp(**kwargs):
        fd = os.open(report_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
        return fd, report_path

    with patch("halspa_runner.test_runner.pty.openpty", return_value=(read_fd, dummy_slave_w)), \
         patch("halspa_runner.test_runner.asyncio.create_subprocess_exec", return_value=process), \
         patch("halspa_runner.test_runner.tempfile.mkstemp", side_effect=fake_mkstemp):
        run_task = asyncio.create_task(runner.run(tmp_path))
        await asyncio.sleep(0.2)
        await runner.cancel()
        result = await run_task

    assert result.status == RunStatus.CANCELLED


@pytest.mark.asyncio
async def test_categories_passed_to_pytest(runner: PytestRunner, tmp_path: Path) -> None:
    report_path = str(tmp_path / "report.jsonl")
    _, patches = _setup_mock([], exit_code=0, report_path=report_path, report_events=[])

    with patches as ctx:
        await runner.run(tmp_path, categories=["000_selftest", "100_power"])

    args = ctx.mock_exec.call_args[0]
    assert "tests/000_selftest" in args
    assert "tests/100_power" in args


@pytest.mark.asyncio
async def test_plugin_args_passed(runner: PytestRunner, tmp_path: Path) -> None:
    report_path = str(tmp_path / "report.jsonl")
    _, patches = _setup_mock([], exit_code=0, report_path=report_path, report_events=[])

    with patches as ctx:
        await runner.run(tmp_path)

    args = ctx.mock_exec.call_args[0]
    assert "-p" in args
    idx = list(args).index("-p")
    assert args[idx + 1] == "halspa_runner.pytest_reporter"

    kwargs = ctx.mock_exec.call_args[1]
    env = kwargs["env"]
    assert "HALSPA_REPORT_FILE" in env
    assert "PYTHONPATH" in env


@pytest.mark.asyncio
async def test_run_error_on_missing_executable(runner: PytestRunner, tmp_path: Path) -> None:
    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    _, slave_fd = os.pipe()

    with patch("halspa_runner.test_runner.pty.openpty", return_value=(read_fd, slave_fd)), \
         patch(
             "halspa_runner.test_runner.asyncio.create_subprocess_exec",
             side_effect=FileNotFoundError("uv not found"),
         ):
        result = await runner.run(tmp_path)

    assert result.status == RunStatus.ERROR


@pytest.mark.asyncio
async def test_empty_report_file(runner: PytestRunner, tmp_path: Path) -> None:
    report_path = str(tmp_path / "report.jsonl")
    _, patches = _setup_mock([], exit_code=1, report_path=report_path, report_events=[])

    with patches:
        result = await runner.run(tmp_path)

    assert result.progress.passed == 0
    assert result.progress.failed == 0
    assert result.progress.total == 0
    assert result.status == RunStatus.FAILED


@pytest.mark.asyncio
async def test_current_test_from_report(runner: PytestRunner, tmp_path: Path) -> None:
    report_path = str(tmp_path / "report.jsonl")
    report_events = [
        {"event": "collected", "total": 1},
        {"event": "result", "nodeid": "tests/test_ping.py::test_ping", "outcome": "passed"},
    ]
    _, patches = _setup_mock(
        [b"tests/test_ping.py::test_ping PASSED\n"], exit_code=0,
        report_path=report_path, report_events=report_events,
    )

    with patches:
        result = await runner.run(tmp_path)

    assert result.progress.current_test == "tests/test_ping.py::test_ping"


@pytest.mark.asyncio
async def test_test_start_callback(runner: PytestRunner, tmp_path: Path) -> None:
    """test_start callback fires when a new test is detected in stdout."""
    report_path = str(tmp_path / "report.jsonl")
    report_events = [
        {"event": "collected", "total": 2},
        {"event": "result", "nodeid": "tests/test_a.py::test_one", "outcome": "passed"},
        {"event": "result", "nodeid": "tests/test_b.py::test_two", "outcome": "passed"},
    ]
    lines = [
        b"tests/test_a.py::test_one PASSED  [ 50%]\n",
        b"tests/test_b.py::test_two PASSED  [100%]\n",
    ]
    _, patches = _setup_mock(lines, exit_code=0, report_path=report_path, report_events=report_events)

    started: list[str] = []

    async def on_test_start(nodeid: str) -> None:
        started.append(nodeid)

    with patches:
        await runner.run(tmp_path, on_test_start=on_test_start)

    assert started == ["tests/test_a.py::test_one", "tests/test_b.py::test_two"]
