"""pytest subprocess orchestration with real-time output streaming."""

import asyncio
import json
import logging
import os
import pty
import re
import signal
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from . import config

logger = logging.getLogger(__name__)

# ANSI escape code pattern
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _find_uv() -> str:
    """Find the uv executable path."""
    import shutil
    path = shutil.which("uv")
    if path:
        return path
    # Common locations
    for candidate in [
        Path.home() / ".local" / "bin" / "uv",
        Path("/usr/local/bin/uv"),
    ]:
        if candidate.exists():
            return str(candidate)
    return "uv"  # fall back to bare name


class RunStatus(Enum):
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass
class RunProgress:
    """Live progress state for a running test."""

    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    total: int = 0
    current_test: str = ""
    start_time: float = field(default_factory=time.monotonic)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.start_time


@dataclass
class RunResult:
    status: RunStatus
    progress: RunProgress
    exit_code: int | None = None


class PytestRunner:
    """Spawns pytest as a subprocess and streams output."""

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._cancelled = False
        self._timed_out = False

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def run(
        self,
        repo_path: Path,
        categories: list[str] | None = None,
        on_line: Any = None,
        on_progress: Any = None,
        on_test_start: Any = None,
    ) -> RunResult:
        """Run pytest in the given repo, streaming output.

        Args:
            repo_path: Path to the *-tests repository root.
            categories: List of test category directory names to run.
                        If None or empty, runs all tests.
            on_line: Async callback called with each output line (str).
            on_progress: Async callback called with RunProgress on each update.
            on_test_start: Async callback called with nodeid when a test starts.

        Returns:
            RunResult with final status.
        """
        self._cancelled = False
        self._timed_out = False
        progress = RunProgress()

        # Create temp file for JSONL report
        report_fd, report_path = tempfile.mkstemp(suffix=".jsonl", prefix="halspa_report_")
        os.close(report_fd)

        try:
            result = await self._run_with_report(
                repo_path, report_path, categories, progress,
                on_line, on_progress, on_test_start,
            )
        finally:
            # Clean up temp file
            try:
                os.unlink(report_path)
            except OSError:
                pass

        return result

    async def _run_with_report(
        self,
        repo_path: Path,
        report_path: str,
        categories: list[str] | None,
        progress: RunProgress,
        on_line: Any,
        on_progress: Any,
        on_test_start: Any,
    ) -> RunResult:
        uv = _find_uv()
        args = [uv, "run", "pytest", "-p", "halspa_runner.pytest_reporter", "-s"]
        if categories:
            args.extend(f"tests/{cat}" for cat in categories)

        # Set up environment: JSONL report path and PYTHONPATH for the plugin
        plugin_src_dir = str(Path(__file__).parent.parent)
        existing_pythonpath = os.environ.get("PYTHONPATH", "")
        pythonpath = f"{plugin_src_dir}:{existing_pythonpath}" if existing_pythonpath else plugin_src_dir

        env = {
            **os.environ,
            "PYTHONUNBUFFERED": "1",
            "HALSPA_REPORT_FILE": report_path,
            "PYTHONPATH": pythonpath,
        }

        # Use a PTY so subprocesses see a terminal and line-buffer output
        master_fd, slave_fd = pty.openpty()

        try:
            self._process = await asyncio.create_subprocess_exec(
                *args,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=str(repo_path),
                env=env,
            )
        except (FileNotFoundError, OSError) as e:
            logger.error("Failed to start pytest: %s", e)
            os.close(master_fd)
            os.close(slave_fd)
            return RunResult(status=RunStatus.ERROR, progress=progress)

        # Close the slave end in the parent — subprocess owns it now
        os.close(slave_fd)

        # Run stdout reader and JSONL reader concurrently
        stdout_task = asyncio.create_task(
            self._read_stdout_pty(master_fd, progress, on_line, on_test_start)
        )
        report_task = asyncio.create_task(
            self._read_report(report_path, progress, on_progress, on_test_start)
        )

        # Wait for stdout to finish (EOF = process done)
        await stdout_task

        # Wait for process to fully exit so the report file is complete
        exit_code = await self._process.wait()

        # Give the report reader a moment to catch up, then cancel it
        await asyncio.sleep(0.2)
        report_task.cancel()
        try:
            await report_task
        except asyncio.CancelledError:
            pass

        if on_progress:
            await on_progress(progress)

        self._process = None

        if self._cancelled:
            status = RunStatus.CANCELLED
        elif self._timed_out:
            status = RunStatus.TIMEOUT
        elif exit_code == 0:
            status = RunStatus.PASSED
        else:
            status = RunStatus.FAILED

        return RunResult(status=status, progress=progress, exit_code=exit_code)

    async def _read_stdout_pty(
        self, master_fd: int, progress: RunProgress,
        on_line: Any, on_test_start: Any,
    ) -> None:
        """Read stdout from a PTY for display.

        PTY ensures subprocesses see a terminal and line-buffer output.
        Detects test boundaries from stdout lines.
        """
        loop = asyncio.get_event_loop()
        buffer = b""
        _last_test_id: str | None = None

        try:
            while True:
                try:
                    data = await asyncio.wait_for(
                        loop.run_in_executor(None, os.read, master_fd, 4096),
                        timeout=config.PYTEST_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    logger.warning("pytest unresponsive for %.0fs, killing",
                                   config.PYTEST_TIMEOUT)
                    self._timed_out = True
                    await self._kill_process()
                    return
                except OSError:
                    break  # PTY closed

                if not data:
                    break  # EOF

                buffer += data
                # Split on \n or \r to handle both newlines and
                # carriage-return progress updates (e.g., esptool)
                while b"\n" in buffer or b"\r" in buffer:
                    # Find the earliest line break
                    nl = buffer.find(b"\n")
                    cr = buffer.find(b"\r")
                    if nl < 0:
                        pos = cr
                    elif cr < 0:
                        pos = nl
                    else:
                        pos = min(nl, cr)
                    line_bytes = buffer[:pos]
                    # Skip \r\n as a single break
                    if pos < len(buffer) - 1 and buffer[pos:pos+2] == b"\r\n":
                        buffer = buffer[pos+2:]
                    else:
                        buffer = buffer[pos+1:]
                    line = _ANSI_RE.sub(
                        "", line_bytes.decode("utf-8", errors="replace")
                    ).strip()

                    if not line:
                        continue

                    # Detect test boundary
                    if line.startswith("tests/") and "::" in line:
                        nodeid = line.split(" ")[0]
                        if nodeid != _last_test_id:
                            _last_test_id = nodeid
                            if on_test_start:
                                await on_test_start(nodeid)

                    if on_line:
                        await on_line(line)

            # Flush remaining buffer
            if buffer:
                line = _ANSI_RE.sub(
                    "", buffer.decode("utf-8", errors="replace")
                ).rstrip("\r").rstrip()
                if line and on_line:
                    await on_line(line)
        finally:
            os.close(master_fd)

    async def _read_report(
        self,
        report_path: str,
        progress: RunProgress,
        on_progress: Any,
        on_test_start: Any,
    ) -> None:
        """Tail the JSONL report file for structured progress updates."""
        # Wait for the file to have content
        report = None
        try:
            while True:
                try:
                    report = open(report_path, "r")
                    break
                except OSError:
                    await asyncio.sleep(0.1)

            while True:
                line = report.readline()
                if not line:
                    await asyncio.sleep(0.05)
                    continue

                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = self._apply_event(event, progress)
                if on_test_start and event_type == "start":
                    await on_test_start(progress.current_test)
                if on_progress and event_type in ("collected", "result"):
                    await on_progress(progress)
        except asyncio.CancelledError:
            raise
        finally:
            if report is not None:
                report.close()

    def _apply_event(self, event: dict, progress: RunProgress) -> str:
        """Apply a JSONL event to the progress state. Returns the event type."""
        event_type = event.get("event", "")
        if event_type == "collected":
            progress.total = event.get("total", 0)
        elif event_type == "start":
            progress.current_test = event.get("nodeid", "")
        elif event_type == "result":
            outcome = event.get("outcome", "")
            nodeid = event.get("nodeid", "")
            progress.current_test = nodeid
            if outcome == "passed":
                progress.passed += 1
            elif outcome == "failed":
                progress.failed += 1
            elif outcome == "skipped":
                progress.skipped += 1
            elif outcome == "error":
                progress.errors += 1
        return event_type

    async def cancel(self) -> None:
        """Cancel the running test: SIGTERM, wait 2s, SIGKILL if needed."""
        if not self._process or self._process.returncode is not None:
            return

        self._cancelled = True
        logger.info("Cancelling pytest subprocess (pid=%d)", self._process.pid)

        try:
            self._process.send_signal(signal.SIGTERM)
        except (ProcessLookupError, OSError):
            return

        try:
            await asyncio.wait_for(self._process.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            await self._kill_process()

    async def _kill_process(self) -> None:
        if self._process and self._process.returncode is None:
            try:
                self._process.kill()
                await self._process.wait()
            except (ProcessLookupError, OSError):
                pass
