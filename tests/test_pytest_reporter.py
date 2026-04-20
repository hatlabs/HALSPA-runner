"""Tests for the pytest JSONL reporter plugin."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def report_file(tmp_path: Path) -> Path:
    return tmp_path / "report.jsonl"


def _run_pytest(tmp_path: Path, test_code: str, report_file: Path, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    """Write a test file and run pytest with the reporter plugin."""
    test_file = tmp_path / "test_sample.py"
    test_file.write_text(test_code)

    env = {**os.environ, "HALSPA_REPORT_FILE": str(report_file)}
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "halspa_runner.pytest_reporter", str(test_file)],
        capture_output=True, text=True, cwd=str(tmp_path), env=env,
    )


def _parse_events(report_file: Path) -> list[dict]:
    return [json.loads(line) for line in report_file.read_text().strip().splitlines()]


def test_collected_event(tmp_path: Path, report_file: Path) -> None:
    result = _run_pytest(tmp_path, """
def test_one(): pass
def test_two(): pass
def test_three(): pass
""", report_file)
    assert result.returncode == 0

    events = _parse_events(report_file)
    collected = [e for e in events if e["event"] == "collected"]
    assert len(collected) == 1
    assert collected[0]["total"] == 3


def test_result_events(tmp_path: Path, report_file: Path) -> None:
    _run_pytest(tmp_path, """
import pytest

def test_pass(): pass

def test_fail(): assert False

@pytest.mark.skip(reason="not ready")
def test_skip(): pass
""", report_file)

    events = _parse_events(report_file)
    results = [e for e in events if e["event"] == "result"]
    outcomes = {e["nodeid"].split("::")[-1]: e["outcome"] for e in results}

    assert outcomes["test_pass"] == "passed"
    assert outcomes["test_fail"] == "failed"
    assert outcomes["test_skip"] == "skipped"


def test_setup_error(tmp_path: Path, report_file: Path) -> None:
    _run_pytest(tmp_path, """
import pytest

@pytest.fixture
def broken():
    raise RuntimeError("fixture boom")

def test_needs_broken(broken):
    pass
""", report_file)

    events = _parse_events(report_file)
    results = [e for e in events if e["event"] == "result"]

    assert len(results) == 1
    assert results[0]["outcome"] == "error"


def test_no_env_var_is_noop(tmp_path: Path) -> None:
    test_file = tmp_path / "test_ok.py"
    test_file.write_text("def test_ok(): pass\n")

    env = {k: v for k, v in os.environ.items() if k != "HALSPA_REPORT_FILE"}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "halspa_runner.pytest_reporter", str(test_file)],
        capture_output=True, text=True, cwd=str(tmp_path), env=env,
    )
    assert result.returncode == 0
