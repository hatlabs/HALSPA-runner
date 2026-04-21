# Plan: Hierarchical Test Browser with Breadcrumb Navigation

## Context

HALSPA-runner's test-selection screen currently shows category directories as flat toggle buttons. User wants to drill into categories to browse subdirectories, test files, and individual test functions — with selection scoped to the current view level only.

The physical start button must be equivalent to pressing "Start Tests" at all times. Users touch the screen only to pick DUT and optionally narrow selections. After a test run, selections persist — pressing the button again re-runs the same tests.

## Architecture

**Navigation model**: Arbitrary-depth filesystem browser. Each level shows dirs, test files, or functions. Click drills in; checkbox selects. Breadcrumb bar shows full path with tappable segments.

**Selection model**: Level-scoped. Navigating away discards selections at that level. "Start Tests" sends whatever is checked at current level as pytest targets.

**Selection persistence**: Frontend syncs current DUT + targets to backend via WebSocket on every selection change. Backend stores them in `StateMachine`. Physical button and re-run after results both use stored state.

**State flow**: After test results are dismissed, system transitions to `DUT_SELECTED` (not `IDLE`), preserving DUT + targets for re-run. Only explicit "back to main menu" clears everything and transitions to `IDLE`.

## Backend Changes

### 1. New browse function in `test_discovery.py`

Add `browse_test_path(repo_path: Path, relative_path: str) -> list[BrowseEntry]`:

- If path is a directory: list subdirs and `test_*.py`/`*_test.py` files. Skip `__pycache__`, `conftest.py`, `__init__.py`.
- If path is a `.py` file: run `pytest --collect-only -q <file>` (5s timeout, cwd=repo_path) to discover test functions. Parse nodeids from output.
- Path traversal guard: reject `..` segments, verify resolved path stays within repo.
- **Error handling**: On pytest non-zero exit, timeout, or parse error, return empty list and log warning. Frontend shows "No tests found" empty state.

Return type:
```python
@dataclass
class BrowseEntry:
    name: str    # "100_power", "test_rails.py", "test_5v_rail"
    type: str    # "directory" | "file" | "function"
    path: str    # relative to repo root: "tests/100_power", "tests/100_power/test_rails.py::test_5v_rail"
```

### 2. New REST endpoint in `app.py`

```
GET /api/duts/{dut_name}/browse?path=<relative_path>
```

Returns `{ "entries": [...], "breadcrumbs": [{"name": "...", "path": "..."}] }`.

Breadcrumbs derived by splitting the path. Empty path = root (categories level).

Resolve `repo_path` by calling `discover_duts()` and matching `dut_name` (consistent with existing `/api/start` endpoint pattern).

On error (DUT not found, path invalid), return appropriate HTTP error with message.

### 3. Modify `test_runner.py` to accept `targets`

`PytestRunner.run()` gets new param `targets: list[str] | None`. When `targets` is provided and non-empty, pass them directly as pytest positional args (no `tests/` prefix — they're already full relative paths/nodeids). When `targets` is None or empty, fall back to existing `categories` logic with `tests/{cat}` prefix. The two params are mutually exclusive at the call site.

### 4. Selection state and dismiss flow in `state.py`

Add to `StateMachine`:
- `_selected_targets: list[str] | None = None` — current test selection (`None` = run all)
- `_selected_repo_path: Path | None = None` — repo path for selected DUT

Method changes:
- `select_dut(dut_name, repo_path)` — stores both, resets targets to `None`, transitions to `DUT_SELECTED`
- `set_targets(targets)` — updates `_selected_targets`, called when frontend syncs selection
- `dismiss_results()` — transitions to `DUT_SELECTED` (not `IDLE`), preserves DUT + targets for re-run
- `deselect_dut()` — clears DUT, targets, repo_path, transitions to `IDLE` (explicit "back to main menu")

Frontend must send a WS `"select-dut"` message when user picks DUT on screen, so backend enters `DUT_SELECTED`. This enables the physical button to work from that state.

### 5. Update start flow and physical button in `app.py`

**New WS message types:**
- `"select-dut"`: frontend sends `{ type: "select-dut", dut: "HALPI2" }` when user picks DUT. Backend calls `discover_duts()` to resolve repo_path, then `state_machine.select_dut(dut, repo_path)`.
- `"select"`: frontend sends `{ type: "select", targets: [...] | null }` whenever selection changes. Backend calls `state_machine.set_targets(targets)`.
- `"deselect"`: frontend sends when user navigates back to main menu. Backend calls `state_machine.deselect_dut()`.

**Physical button (`_handle_button`)** updated:
- `IDLE` state with sandwich detected → auto-select DUT via `select_dut()`, targets=None, start
- `DUT_SELECTED` state → start run with stored `_selected_targets` from state machine
- `RESULTS_PASS/RESULTS_FAIL` → dismiss results (→ `DUT_SELECTED`), then start run with same targets

**`_start_test_run`** reads DUT + targets + repo_path from state machine (single source of truth).

**`StartRequest`** and WS `start` message: accept `targets: list[str] | None` instead of `categories`. Store targets in state machine before starting.

## Frontend Changes

### 6. Rewrite `test-selection.js` as hierarchical browser

**Properties:**
- `dut`, `currentPath` (string), `entries` (array), `breadcrumbs` (array)
- `loading`, `error` (string|null), `runAll`, `selected` (Set of paths), `starting`

**Layout** (same flex-column structure):
- **Header**: Breadcrumb bar (tappable segments, 48px+ targets, horizontal scroll via `overflow-x: auto`)
- **Content**: "Run All" toggle + entry rows. Show spinner during fetch. Show "No tests found" when entries empty.
- **Footer**: "Start Tests" button

**Entry row** (two tap zones):
- Left: checkbox area (56px wide, toggles selection)
- Right: label + type icon + drill chevron (click drills for dir/file, toggles for function)

**Navigation:**
- `_drillInto(entry)` → sets `currentPath = entry.path` → triggers fetch via `GET /api/duts/{dut}/browse?path=...`
- `_navigateToBreadcrumb(crumb)` → sets `currentPath = crumb.path`
- `_back()` → pops last segment from path, or dispatches `back` event at root

**Selection sync:**
- On every selection change, dispatch `select-targets` event to app-shell
- App-shell forwards to backend via WS: `{ type: "select", targets }`
- Resets on path change (level-scoped)
- Same toggle logic as current (runAll ↔ individual)

**Start dispatch:**
```javascript
detail: { dut: this.dut.name, targets: this.runAll ? null : [...this.selected] }
```

### 7. Update `app-shell.js`

- Remove `selectedCategories`, `runAll` properties (now internal to test-selection)
- On DUT selection from main menu: send WS `{ type: "select-dut", dut }` to backend
- Listen for `select-targets` event → send WS `{ type: "select", targets }`
- `_onStartTests`: extract `targets`, send via WS `{ type: "start", dut, targets }`
- `_onDismiss` returns to test-selection screen (keeps `selectedDut`)
- `_onBack` (from test-selection root) sends WS `{ type: "deselect" }`, clears `selectedDut` → main menu
- After results dismiss, render test-selection (not main menu) since `selectedDut` is preserved

## Implementation Order

1. `state.py` — add target/repo_path storage, dismiss → DUT_SELECTED, deselect_dut() (independent)
2. `test_discovery.py` — browse function with error handling (independent)
3. `test_runner.py` — add `targets` param (independent)
4. `app.py` — browse endpoint, select-dut/select/deselect WS messages, button handler update (depends on 1-3)
5. `test-selection.js` — full rewrite with loading/error/empty states (depends on 4 for API)
6. `app-shell.js` — wire DUT selection, targets sync, dismiss flow (depends on 5)

## Verification

**API Layer:**
1. Browse endpoint returns correct entries/breadcrumbs at each level. Path traversal guard rejects `..`.
2. Browse on `.py` file returns test functions. On error/timeout, returns empty list.

**UI Navigation:**
3. Hierarchy navigation works on touchscreen. Breadcrumbs tappable. Selections scoped per level.
4. Loading spinner shown during browse fetches. "No tests found" shown for empty results.
5. Start runs only selected targets at current level.

**Button & Persistence:**
6. Physical button with DUT selected + targets set → runs those targets.
7. On results screen → button dismisses and re-runs same tests with same DUT + targets.
8. With no DUT but sandwich detected → runs all for that DUT.
9. After results dismiss, test-selection screen shows with previous DUT preserved.
10. Back to main menu from test-selection sends deselect, clears backend state.

## Files to Modify

- `HALSPA-runner/src/halspa_runner/state.py`
- `HALSPA-runner/src/halspa_runner/test_discovery.py`
- `HALSPA-runner/src/halspa_runner/test_runner.py`
- `HALSPA-runner/src/halspa_runner/app.py`
- `HALSPA-runner/frontend/src/screens/test-selection.js`
- `HALSPA-runner/frontend/src/app-shell.js`
