"""Lightweight pytest plugin that writes JSONL progress to a file.

Loaded by the test runner via ``-p halspa_runner.pytest_reporter``.
The report file path is read from the ``HALSPA_REPORT_FILE`` environment
variable.  If the variable is not set the plugin is a silent no-op, so
it is safe to load unconditionally.

Each line is a JSON object, flushed immediately:

    {"event": "collected", "total": 23}
    {"event": "result", "nodeid": "tests/...", "outcome": "passed"}
"""

import json
import os

_report_file = None


def pytest_configure(config):
    global _report_file
    path = os.environ.get("HALSPA_REPORT_FILE")
    if not path:
        return
    try:
        _report_file = open(path, "w", buffering=1)  # line-buffered
    except OSError:
        _report_file = None


def pytest_unconfigure(config):
    global _report_file
    if _report_file is not None:
        try:
            _report_file.close()
        except OSError:
            pass
        _report_file = None


def _write_result(nodeid: str, outcome: str) -> None:
    if _report_file is None:
        return
    try:
        _report_file.write(json.dumps({
            "event": "result",
            "nodeid": nodeid,
            "outcome": outcome,
        }) + "\n")
    except OSError:
        pass


def pytest_collection_modifyitems(items):
    if _report_file is None:
        return
    try:
        _report_file.write(json.dumps({"event": "collected", "total": len(items)}) + "\n")
    except OSError:
        pass


def pytest_runtest_logstart(nodeid, location):
    if _report_file is None:
        return
    try:
        _report_file.write(json.dumps({
            "event": "start",
            "nodeid": nodeid,
        }) + "\n")
    except OSError:
        pass


def pytest_runtest_logreport(report):
    if _report_file is None:
        return

    # Setup failure means the test never ran — report as error.
    if report.when == "setup" and report.failed:
        _write_result(report.nodeid, "error")
        return

    # Skipped tests are reported during setup (skip marker) or call (skip()).
    if report.skipped:
        # Only report once: setup phase for marker skips, call phase for skip().
        if report.when in ("setup", "call"):
            _write_result(report.nodeid, "skipped")
        return

    # Only report the call phase for normal results.
    if report.when != "call":
        return

    _write_result(report.nodeid, report.outcome)
