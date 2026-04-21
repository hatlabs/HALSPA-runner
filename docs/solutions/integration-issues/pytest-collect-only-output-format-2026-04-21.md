---
title: "pytest --collect-only requires -qq for flat nodeid output"
date: 2026-04-21
category: integration-issues
module: test-discovery
problem_type: integration_issue
component: tooling
symptoms:
  - "Browsing into a test file shows 'No tests found' despite tests existing"
  - "pytest --collect-only -q returns tree-format output instead of flat nodeids"
  - "Parser returns empty list — no error indication"
root_cause: wrong_api
resolution_type: code_fix
severity: high
tags:
  - pytest
  - test-discovery
  - subprocess-output
  - collect-only
  - quiet-flag
---

# pytest --collect-only requires -qq for flat nodeid output

## Problem

When using `pytest --collect-only` for programmatic test function discovery, the `-q` (quiet) flag produces tree-format output in pytest 9.x, not the flat nodeid-per-line format expected by the parser. This caused the hierarchical test browser to silently return zero functions for any test file.

## Symptoms

- Frontend test browser displays "No tests found" when drilling into a test file
- No errors in backend logs (parser silently finds zero matches)
- Manual `pytest --collect-only -q <file>` shows tests are collectible, but in tree format:
  ```
  <Dir tests>
    <Dir 100_power>
      <Module 101_power_test.py>
        <Function test_input_voltage_present>
  ```
- Issue appeared on Pi (pytest 9.0.2) — may not reproduce on machines with older pytest

## What Didn't Work

- **Tried `--noconftest`**: Assumed the DUT repo's conftest.py was capturing stdout (it logged "All stdout captured to log files"). Still produced tree format — the issue was the quiet-level flag, not conftest interference.
- **Tried `--no-header`**: Reduced some noise but didn't change the output format from tree to flat.

## Solution

Change `-q` to `-qq` in the subprocess invocation:

```python
# Before (broken — tree format)
proc = await asyncio.create_subprocess_exec(
    uv, "run", "pytest", "--collect-only", "-q", rel_file,
    ...
)

# After (fixed — flat nodeid format)
proc = await asyncio.create_subprocess_exec(
    uv, "run", "pytest", "--collect-only", "-qq", rel_file,
    ...
)
```

With `-qq`, output becomes parseable flat nodeids:
```
tests/100_power/101_power_test.py::test_input_voltage_present
tests/100_power/101_power_test.py::test_no_fault_at_power_on
tests/100_power/101_power_test.py::test_quiescent_current
```

## Why This Works

In pytest 9.x, the quiet flag has three levels:
- No flag: verbose tree with full details
- `-q`: suppressed tree (less detail, still hierarchical)
- `-qq`: flat nodeid-per-line format

The parser regex filters lines matching `<rel_file>::<function>`. Tree-format lines like `<Function test_name>` never match, producing an empty result set.

## Prevention

- When parsing CLI tool output programmatically, verify expected format against the deployed tool version — output formats change across major versions
- Add a test that runs `pytest --collect-only -qq` against a known test file and asserts the output contains `::` nodeids
- Log raw subprocess stdout on zero results (the silent empty-list return made debugging harder)
- Pin the quiet-level flag in comments: `# -qq required for flat nodeid format (not -q)`

## Related Issues

- [HALSPA-runner PR #20](https://github.com/hatlabs/HALSPA-runner/pull/20) — Hierarchical test browser feature where this was discovered
- `docs/plan-hierarchical-test-browser.md` — Feature plan that originally specified `-q`
