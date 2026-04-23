---
title: "pytest Marker Awareness: AST Scan + Tautological markexpr Bypass"
date: 2026-04-23
category: best-practices
module: halspa-runner
problem_type: best_practice
component: test_runner
severity: medium
applies_when:
  - "Running specific test functions that are gated by a conftest skip hook"
  - "Detecting pytest markers on test functions without executing them"
  - "Propagating marker metadata from test files to a UI or API layer"
tags:
  - pytest
  - ast-scan
  - markers
  - conftest
  - noauto
  - markexpr
---

# pytest Marker Awareness: AST Scan + Tautological markexpr Bypass

## Context

HALSPA test suites use `@pytest.mark.noauto` on functions that require manual setup (physical interaction, specific hardware state). The conftest skip hook pattern looks like:

```python
def pytest_collection_modifyitems(config, items):
    keywordexpr = config.option.keyword
    markexpr = config.option.markexpr
    if keywordexpr or markexpr:
        return  # User explicitly filtered — honour it
    for item in items:
        if item.get_closest_marker("noauto"):
            item.add_marker(pytest.mark.skip(reason="noauto: run with -k or -m"))
```

When running a targeted nodeid (`tests/foo/test_bar.py::test_manual_fn`) through the runner UI, the test was being skipped because no `-k`/`-m` filter was set — even though the user explicitly selected that specific test.

## Guidance

### 1. Detect markers via AST, not subprocess

Use Python's `ast` module to scan source files for `@pytest.mark.noauto` decorators. This is synchronous, has no environmental dependencies, and is fast enough to run inline.

```python
import ast

def _scan_noauto_markers(source_file: Path) -> set[str]:
    try:
        source = source_file.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(source_file))
    except (OSError, SyntaxError):
        return set()

    noauto_funcs: set[str] = set()
    for node in ast.walk(tree):
        # AsyncFunctionDef is a separate node type from FunctionDef
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            # Unwrap @pytest.mark.noauto("reason") call form
            dec_node = dec.func if isinstance(dec, ast.Call) else dec
            if (
                isinstance(dec_node, ast.Attribute)
                and dec_node.attr == "noauto"
                and isinstance(dec_node.value, ast.Attribute)
                and dec_node.value.attr == "mark"
                and isinstance(dec_node.value.value, ast.Name)
                and dec_node.value.value.id == "pytest"
            ):
                noauto_funcs.add(node.name)
                break
    return noauto_funcs
```

Two non-obvious requirements:
- **`ast.AsyncFunctionDef` is a separate node type.** `isinstance(node, ast.FunctionDef)` silently misses all `async def` functions. Always check both.
- **Unwrap `ast.Call` for the call form.** `@pytest.mark.noauto("reason")` produces a `Call` node whose `.func` is the attribute chain. Without unwrapping, only the bare `@pytest.mark.noauto` form is detected.

### 2. Bypass the conftest skip with a tautological markexpr

The conftest hook's early-return condition is `if keywordexpr or markexpr`. Any non-empty string for `markexpr` will trigger the early return and bypass the skip logic. Use a tautological expression that matches every test:

```python
args.extend(["-m", "noauto or not noauto"])
```

Every test either has the `noauto` marker or doesn't — so `noauto or not noauto` is always true. The sole effect is setting `markexpr` to a truthy value.

**Important limitation:** This bypasses ALL conftest skip logic for the entire batch, not just the noauto skip. If the conftest has other skip conditions gated on `markexpr`, those are also bypassed. Only inject this flag when at least one target is a noauto-marked function.

### 3. Strip parameterize suffix before AST set lookup

pytest parameterized test nodeids include a `[param]` suffix: `test_fn[param1-param2]`. The AST scanner returns bare function names (`test_fn`). Strip the suffix before the set lookup:

```python
# When checking runner targets
file_part, func_name = target.rsplit("::", 1)
func_name_base = func_name.split("[")[0]  # strip [param1-param2]
if func_name_base in noauto:
    ...

# When tagging browse entries from pytest --collect-only output
func_name_base = entry.path.rsplit("::", 1)[-1].split("[")[0]
if func_name_base in noauto:
    entry.markers = ["noauto"]
```

## When to Apply

- A conftest skip hook uses the `if keywordexpr or markexpr: return` pattern
- The UI or API needs to know whether a specific test is noauto-gated before the user runs it
- Targeted test runs (specific nodeids) need to bypass conftest skips automatically

## When NOT to Apply

- Module-level `pytestmark = [pytest.mark.noauto]` — AST scan is limited to direct function decorators; module-level marks propagate differently and are out of scope for this pattern
- When the conftest skip logic is more complex (e.g., checks markers directly rather than relying on `markexpr`) — verify the hook's skip condition before applying the bypass

## Related

- hatlabs/HALSPA-runner#38 — PR implementing noauto marker awareness
- [Test File Discovery: Parse Config Directly](./test-file-discovery-parse-config-not-subprocess-2026-04-23.md) — companion pattern for test file discovery without subprocess
