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
_call_outcomes: dict[str, str] = {}


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

    if report.when == "setup":
        if report.skipped:
            _write_result(report.nodeid, "skipped")
        return

    # The call outcome is held until teardown, so a test whose fixture
    # teardown fails is reported once, as an error, like pytest counts it.
    if report.when == "call":
        _call_outcomes[report.nodeid] = "skipped" if report.skipped else report.outcome
        return

    outcome = _call_outcomes.pop(report.nodeid, None)
    if outcome is None:
        return
    if report.failed and outcome != "failed":
        outcome = "error"
    _write_result(report.nodeid, outcome)
