"""pytest subprocess orchestration with real-time output streaming."""

import asyncio
import logging
import os
import re
import signal
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from . import config

logger = logging.getLogger(__name__)

# Regex to detect pytest result lines like "PASSED", "FAILED", "SKIPPED", "ERROR"
_RESULT_RE = re.compile(
    r"^tests/.*\s(PASSED|FAILED|SKIPPED|ERROR|XFAIL|XPASS)\s*(\(.*\))?\s*$"
)

# ANSI escape code pattern
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


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

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def run(
        self,
        repo_path: Path,
        categories: list[str] | None = None,
        on_line: Any = None,
        on_progress: Any = None,
    ) -> RunResult:
        """Run pytest in the given repo, streaming output.

        Args:
            repo_path: Path to the *-tests repository root.
            categories: List of test category directory names to run.
                        If None or empty, runs all tests.
            on_line: Async callback called with each output line (str).
            on_progress: Async callback called with RunProgress on each update.

        Returns:
            RunResult with final status.
        """
        self._cancelled = False
        progress = RunProgress()

        args = ["uv", "run", "pytest"]
        if categories:
            args.extend(f"tests/{cat}" for cat in categories)

        env = {**os.environ, "PYTHONUNBUFFERED": "1"}

        try:
            self._process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(repo_path),
                env=env,
            )
        except (FileNotFoundError, OSError) as e:
            logger.error("Failed to start pytest: %s", e)
            return RunResult(status=RunStatus.ERROR, progress=progress)

        last_output_time = time.monotonic()
        timeout = config.PYTEST_TIMEOUT

        assert self._process.stdout is not None
        while True:
            try:
                line_bytes = await asyncio.wait_for(
                    self._process.stdout.readline(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                logger.warning("pytest unresponsive for %.0fs, killing", timeout)
                await self._kill_process()
                return RunResult(
                    status=RunStatus.TIMEOUT,
                    progress=progress,
                    exit_code=None,
                )

            if not line_bytes:
                break  # EOF — process has finished

            last_output_time = time.monotonic()
            line = _ANSI_RE.sub("", line_bytes.decode("utf-8", errors="replace")).rstrip()

            # Update progress from pytest output
            match = _RESULT_RE.match(line)
            if match:
                result = match.group(1)
                if result == "PASSED" or result == "XPASS":
                    progress.passed += 1
                elif result == "FAILED":
                    progress.failed += 1
                elif result == "SKIPPED" or result == "XFAIL":
                    progress.skipped += 1
                elif result == "ERROR":
                    progress.errors += 1

            # Extract current test name from collection/running lines
            if "::" in line and not line.startswith(" "):
                progress.current_test = line.split(" ")[0]

            if on_line:
                await on_line(line)
            if on_progress:
                await on_progress(progress)

        exit_code = await self._process.wait()
        self._process = None

        if self._cancelled:
            status = RunStatus.CANCELLED
        elif exit_code == 0:
            status = RunStatus.PASSED
        else:
            status = RunStatus.FAILED

        return RunResult(status=status, progress=progress, exit_code=exit_code)

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
