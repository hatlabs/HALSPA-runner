"""Tests for test_runner module with mock subprocesses."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from halspa_runner.test_runner import RunStatus, PytestRunner


@pytest.fixture
def runner() -> PytestRunner:
    return PytestRunner()


async def _make_mock_process(
    lines: list[bytes], exit_code: int = 0,
) -> MagicMock:
    """Create a mock asyncio subprocess with given output lines."""
    process = MagicMock()
    process.pid = 12345
    process.returncode = None

    line_iter = iter(lines + [b""])  # Empty bytes = EOF

    async def readline() -> bytes:
        return next(line_iter)

    process.stdout = MagicMock()
    process.stdout.readline = readline

    async def wait() -> int:
        process.returncode = exit_code
        return exit_code

    process.wait = wait
    return process


@pytest.mark.asyncio
async def test_successful_run(runner: PytestRunner, tmp_path: Path) -> None:
    lines = [
        b"tests/000_selftest/test_ping.py::test_ping PASSED\n",
        b"tests/000_selftest/test_ping.py::test_pong PASSED\n",
    ]
    mock_proc = await _make_mock_process(lines, exit_code=0)

    with patch("halspa_runner.test_runner.asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await runner.run(tmp_path)

    assert result.status == RunStatus.PASSED
    assert result.progress.passed == 2
    assert result.progress.failed == 0
    assert result.exit_code == 0


@pytest.mark.asyncio
async def test_failed_run(runner: PytestRunner, tmp_path: Path) -> None:
    lines = [
        b"tests/100_power/test_5v.py::test_5v_output PASSED\n",
        b"tests/100_power/test_5v.py::test_overcurrent FAILED\n",
    ]
    mock_proc = await _make_mock_process(lines, exit_code=1)

    with patch("halspa_runner.test_runner.asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await runner.run(tmp_path)

    assert result.status == RunStatus.FAILED
    assert result.progress.passed == 1
    assert result.progress.failed == 1
    assert result.exit_code == 1


@pytest.mark.asyncio
async def test_skipped_tests(runner: PytestRunner, tmp_path: Path) -> None:
    lines = [
        b"tests/200_controller/test_i2c.py::test_scan PASSED\n",
        b"tests/200_controller/test_i2c.py::test_optional SKIPPED (no hw)\n",
    ]
    mock_proc = await _make_mock_process(lines, exit_code=0)

    with patch("halspa_runner.test_runner.asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await runner.run(tmp_path)

    assert result.progress.passed == 1
    assert result.progress.skipped == 1


@pytest.mark.asyncio
async def test_on_line_callback(runner: PytestRunner, tmp_path: Path) -> None:
    lines = [
        b"tests/000_selftest/test_ping.py::test_ping PASSED\n",
    ]
    mock_proc = await _make_mock_process(lines, exit_code=0)
    received_lines: list[str] = []

    async def on_line(line: str) -> None:
        received_lines.append(line)

    with patch("halspa_runner.test_runner.asyncio.create_subprocess_exec", return_value=mock_proc):
        await runner.run(tmp_path, on_line=on_line)

    assert any("test_ping PASSED" in line for line in received_lines)


@pytest.mark.asyncio
async def test_strips_ansi_codes(runner: PytestRunner, tmp_path: Path) -> None:
    lines = [
        b"\x1b[32mtests/000_selftest/test_ping.py::test_ping PASSED\x1b[0m\n",
    ]
    mock_proc = await _make_mock_process(lines, exit_code=0)
    received_lines: list[str] = []

    async def on_line(line: str) -> None:
        received_lines.append(line)

    with patch("halspa_runner.test_runner.asyncio.create_subprocess_exec", return_value=mock_proc):
        await runner.run(tmp_path, on_line=on_line)

    assert received_lines[0] == "tests/000_selftest/test_ping.py::test_ping PASSED"
    assert "\x1b" not in received_lines[0]


@pytest.mark.asyncio
async def test_cancel(runner: PytestRunner, tmp_path: Path) -> None:
    # Simulate a long-running process
    process = MagicMock()
    process.pid = 12345
    process.returncode = None

    read_count = 0

    async def readline() -> bytes:
        nonlocal read_count
        read_count += 1
        if read_count == 1:
            return b"tests/000_selftest/test_slow.py::test_slow "
        # Hang until cancelled
        await asyncio.sleep(10)
        return b""

    process.stdout = MagicMock()
    process.stdout.readline = readline

    cancel_called = False

    def send_signal(sig: int) -> None:
        nonlocal cancel_called
        cancel_called = True

    process.send_signal = send_signal

    async def wait() -> int:
        if cancel_called:
            process.returncode = -15
            return -15
        await asyncio.sleep(10)
        process.returncode = 0
        return 0

    process.wait = wait

    with patch("halspa_runner.test_runner.asyncio.create_subprocess_exec", return_value=process):
        # Start run in background, cancel after brief delay
        run_task = asyncio.create_task(runner.run(tmp_path))
        await asyncio.sleep(0.1)
        await runner.cancel()
        result = await run_task

    assert result.status == RunStatus.CANCELLED


@pytest.mark.asyncio
async def test_categories_passed_to_pytest(runner: PytestRunner, tmp_path: Path) -> None:
    mock_proc = await _make_mock_process([], exit_code=0)

    with patch("halspa_runner.test_runner.asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await runner.run(tmp_path, categories=["000_selftest", "100_power"])

    args = mock_exec.call_args[0]
    assert "tests/000_selftest" in args
    assert "tests/100_power" in args


@pytest.mark.asyncio
async def test_run_error_on_missing_executable(runner: PytestRunner, tmp_path: Path) -> None:
    with patch(
        "halspa_runner.test_runner.asyncio.create_subprocess_exec",
        side_effect=FileNotFoundError("uv not found"),
    ):
        result = await runner.run(tmp_path)

    assert result.status == RunStatus.ERROR
