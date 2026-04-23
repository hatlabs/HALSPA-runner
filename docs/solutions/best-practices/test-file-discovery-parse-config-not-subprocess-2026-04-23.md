---
title: "Test File Discovery: Parse Config Directly, Don't Shell Out"
date: 2026-04-23
category: best-practices
module: halspa-runner
problem_type: best_practice
component: testing_framework
severity: medium
applies_when:
  - "Discovering test files with non-standard naming patterns (e.g., *_action.py)"
  - "Building file browsers or tree views over test directories"
  - "Running in a service context (systemd) where environment leaks from parent process"
tags:
  - test-discovery
  - pyproject-toml
  - subprocess-isolation
  - abstraction-level
  - pytest-config
---

# Test File Discovery: Parse Config Directly, Don't Shell Out

## Context

HALSPA-runner's test discovery showed 2 of 6 files in the 200_controller category. The cause: `_is_test_file()` hardcoded `test_*.py` and `*_test.py` patterns, missing `*_action.py` files configured in the repo's `pyproject.toml` `python_files` setting.

The natural instinct was to delegate to pytest — run `pytest --collect-only` as a subprocess and parse the output. This would respect all pytest config automatically. But in the service context (systemd unit running uvicorn), this created a cascade of environment workarounds:

1. **VIRTUAL_ENV leak** — the runner's venv was inherited → uv resolved the wrong project → had to strip VIRTUAL_ENV
2. **conftest.py GPIO hang** — conftest imports hardware modules (`halpi2`) at module level → `gpiod.request_lines()` blocks when GPIO is still held from previous test run → had to add `--noconftest`
3. **Broken imports** — `--noconftest` broke `dut_config.py` imports → had to inject repo root into PYTHONPATH
4. **Partial failures** — some test files still failed to import → had to accept exit code 2

Each workaround fixed the previous one's side effect. CE code review correctly identified this as a fragile house of cards.

## Guidance

Distinguish between two levels of test discovery:

- **File discovery** (which `.py` files are test files?) → read `python_files` from `pyproject.toml` and match with `fnmatch`
- **Function discovery** (which functions in a file are tests?) → delegate to `pytest --collect-only` (this legitimately needs pytest's import machinery)

For file discovery, parse the config directly:

```python
import fnmatch
import tomllib

_DEFAULT_PYTHON_FILES = ["test_*.py", "*_test.py"]

def _read_python_files(repo_path: Path) -> list[str]:
    pyproject = repo_path / "pyproject.toml"
    if not pyproject.is_file():
        return _DEFAULT_PYTHON_FILES
    try:
        with open(pyproject, "rb") as f:
            config = tomllib.load(f)
        patterns = (config.get("tool", {}).get("pytest", {})
                    .get("ini_options", {}).get("python_files"))
        if patterns and isinstance(patterns, list):
            return patterns
    except (tomllib.TOMLDecodeError, OSError) as e:
        logger.warning("Failed to read pyproject.toml: %s", e)
    return _DEFAULT_PYTHON_FILES

def _is_test_file(name: str, patterns: list[str]) -> bool:
    return name.endswith(".py") and any(fnmatch.fnmatch(name, p) for p in patterns)
```

Then use `_is_test_file()` in a normal filesystem scan (`os.walk` or `iterdir`).

## Why This Matters

The subprocess approach introduced four environment-specific workarounds for a problem that didn't require a subprocess at all. Each workaround was individually logical but collectively fragile:

- **Untestable**: unit tests had to mock the entire subprocess boundary (`_run_collect`), so the env manipulation, `--noconftest`, PYTHONPATH injection, and exit code handling were never exercised
- **Silent failures**: collection errors returned empty lists with no error channel to the UI
- **Service-specific**: the workarounds only mattered in the systemd context, not in development
- **Coupled to pytest internals**: exit codes, output format (`-qq`), and `--noconftest` behavior could change across pytest versions

The filesystem approach has none of these problems. It reads a TOML file and matches filenames — testable, fast, no environmental dependencies.

## When to Apply

- You need to know which files are test files (for browsing, listing, filtering)
- You do NOT need pytest's import machinery, fixture resolution, or marker processing
- You're running in a constrained environment (service, container, CI) where subprocess env may differ from development

Do NOT apply when:
- You need function-level discovery (which test functions exist in a file) — that requires pytest
- You need to evaluate markers, parametrize, or fixtures — those are runtime concepts

## Examples

**Before (subprocess with workaround chain):**

```python
async def _browse_directory(repo_path, directory):
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env["PYTHONPATH"] = str(repo_path)
    proc = await asyncio.create_subprocess_exec(
        uv, "run", "pytest", "--collect-only", "-qq", "--noconftest", rel_dir,
        cwd=str(repo_path), env=env, ...)
    # parse subprocess output, handle exit code 2, timeout, etc.
```

**After (config parsing + filesystem scan):**

```python
def _browse_directory(repo_path, directory, patterns):
    entries = []
    for item in sorted(directory.iterdir()):
        if item.is_dir() and _dir_has_tests(item, patterns):
            entries.append(BrowseEntry(name=item.name, type="directory", ...))
        elif _is_test_file(item.name, patterns):
            entries.append(BrowseEntry(name=item.name, type="file", ...))
    return entries
```

Sync, no subprocess, no env manipulation, directly testable with real filesystem fixtures.

## Related

- [pytest --collect-only output format](../integration-issues/pytest-collect-only-output-format-2026-04-21.md) — predecessor issue with `-q` vs `-qq` flag; the subprocess approach's first failure point (now superseded for file discovery)
- hatlabs/HALSPA-runner#37 — PR implementing this approach
