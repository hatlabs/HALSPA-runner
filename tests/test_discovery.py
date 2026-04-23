"""Tests for test_discovery module."""

from pathlib import Path

import pytest

from unittest.mock import AsyncMock, patch

from halspa_runner.test_discovery import (
    BrowseEntry,
    BrowseError,
    DUT,
    Category,
    _is_test_file,
    _read_python_files,
    _scan_noauto_markers,
    browse_test_path,
    discover_duts,
)


def _make_test_repo(tmp_path: Path, name: str, categories: list[str]) -> Path:
    """Create a minimal *-tests directory structure."""
    repo = tmp_path / name
    tests_dir = repo / "tests"
    tests_dir.mkdir(parents=True)
    for cat in categories:
        (tests_dir / cat).mkdir()
    return repo


def test_discovers_single_dut(tmp_path: Path) -> None:
    _make_test_repo(tmp_path, "HALPI2-tests", ["000_selftest", "100_power"])

    duts = discover_duts(tmp_path)

    assert len(duts) == 1
    assert duts[0].name == "HALPI2"
    assert len(duts[0].categories) == 2
    assert duts[0].categories[0].name == "000_selftest"
    assert duts[0].categories[1].name == "100_power"


def test_discovers_multiple_duts(tmp_path: Path) -> None:
    _make_test_repo(tmp_path, "HALPI2-tests", ["000_selftest"])
    _make_test_repo(tmp_path, "HALSER-tests", ["000_selftest", "100_canbus"])

    duts = discover_duts(tmp_path)

    assert len(duts) == 2
    assert duts[0].name == "HALPI2"
    assert duts[1].name == "HALSER"


def test_follows_symlinks(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    _make_test_repo(actual, "HALPI2-tests", ["000_selftest"])

    scan_dir = tmp_path / "scan"
    scan_dir.mkdir()
    (scan_dir / "HALPI2-tests").symlink_to(actual / "HALPI2-tests")

    duts = discover_duts(scan_dir)

    assert len(duts) == 1
    assert duts[0].name == "HALPI2"


def test_skips_dir_without_tests_subdir(tmp_path: Path) -> None:
    (tmp_path / "HALPI2-tests").mkdir()
    # No tests/ subdirectory

    duts = discover_duts(tmp_path)

    assert len(duts) == 0


def test_skips_dir_without_numbered_categories(tmp_path: Path) -> None:
    repo = tmp_path / "HALPI2-tests"
    tests_dir = repo / "tests"
    tests_dir.mkdir(parents=True)
    # Only non-numbered entries
    (tests_dir / "conftest.py").touch()
    (tests_dir / "__pycache__").mkdir()

    duts = discover_duts(tmp_path)

    assert len(duts) == 0


def test_empty_scan_dir(tmp_path: Path) -> None:
    duts = discover_duts(tmp_path)
    assert len(duts) == 0


def test_nonexistent_scan_dir(tmp_path: Path) -> None:
    duts = discover_duts(tmp_path / "does_not_exist")
    assert len(duts) == 0


def test_ignores_non_tests_directories(tmp_path: Path) -> None:
    _make_test_repo(tmp_path, "HALPI2-tests", ["000_selftest"])
    # Create a directory that doesn't match the pattern
    other = tmp_path / "HALSPA-client"
    other.mkdir()
    (other / "tests").mkdir()
    (other / "tests" / "000_unit").mkdir()

    duts = discover_duts(tmp_path)

    assert len(duts) == 1
    assert duts[0].name == "HALPI2"


def test_categories_sorted_by_name(tmp_path: Path) -> None:
    _make_test_repo(
        tmp_path, "HALPI2-tests",
        ["300_canbus", "000_selftest", "100_power", "200_controller"],
    )

    duts = discover_duts(tmp_path)

    names = [c.name for c in duts[0].categories]
    assert names == ["000_selftest", "100_power", "200_controller", "300_canbus"]


# --- _read_python_files tests ---


def test_read_python_files_from_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\npython_files = ["*_test.py", "*_action.py"]\n'
    )

    patterns = _read_python_files(tmp_path)

    assert patterns == ["*_test.py", "*_action.py"]


def test_read_python_files_defaults_without_pyproject(tmp_path: Path) -> None:
    patterns = _read_python_files(tmp_path)

    assert patterns == ["test_*.py", "*_test.py"]


def test_read_python_files_defaults_without_python_files_key(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\naddopts = '-v'\n")

    patterns = _read_python_files(tmp_path)

    assert patterns == ["test_*.py", "*_test.py"]


# --- _is_test_file tests ---


def test_is_test_file_default_patterns() -> None:
    patterns = ["test_*.py", "*_test.py"]
    assert _is_test_file("test_rails.py", patterns)
    assert _is_test_file("usb_vbus_test.py", patterns)
    assert not _is_test_file("conftest.py", patterns)
    assert not _is_test_file("__init__.py", patterns)
    assert not _is_test_file("helper.py", patterns)


def test_is_test_file_custom_patterns() -> None:
    patterns = ["*_test.py", "*_action.py"]
    assert _is_test_file("usb_vbus_test.py", patterns)
    assert _is_test_file("flash_controller_action.py", patterns)
    assert not _is_test_file("test_rails.py", patterns)
    assert not _is_test_file("conftest.py", patterns)


# --- browse_test_path tests ---


def _make_browse_repo(tmp_path: Path, python_files: list[str] | None = None) -> Path:
    """Create a repo with tests/ structure for browse_test_path tests."""
    repo = tmp_path / "repo"
    repo.mkdir()
    if python_files is not None:
        patterns_str = ", ".join(f'"{p}"' for p in python_files)
        (repo / "pyproject.toml").write_text(
            f"[tool.pytest.ini_options]\npython_files = [{patterns_str}]\n"
        )
    return repo


@pytest.mark.asyncio
async def test_browse_root_returns_categories(tmp_path: Path) -> None:
    repo = _make_browse_repo(tmp_path)
    tests_dir = repo / "tests"
    (tests_dir / "100_power").mkdir(parents=True)
    (tests_dir / "100_power" / "test_rails.py").touch()
    (tests_dir / "200_thermal").mkdir()
    (tests_dir / "200_thermal" / "test_temp.py").touch()

    entries = await browse_test_path(repo, "")

    names = [e.name for e in entries]
    assert "100_power" in names
    assert "200_thermal" in names
    assert all(e.type == "directory" for e in entries)


@pytest.mark.asyncio
async def test_browse_subdirectory_returns_files(tmp_path: Path) -> None:
    repo = _make_browse_repo(tmp_path)
    power_dir = repo / "tests" / "100_power"
    power_dir.mkdir(parents=True)
    (power_dir / "test_rails.py").touch()

    entries = await browse_test_path(repo, "tests/100_power")

    assert len(entries) == 1
    assert entries[0].name == "test_rails.py"
    assert entries[0].type == "file"


@pytest.mark.asyncio
async def test_browse_respects_custom_python_files(tmp_path: Path) -> None:
    repo = _make_browse_repo(tmp_path, python_files=["*_test.py", "*_action.py"])
    ctrl_dir = repo / "tests" / "200_controller"
    ctrl_dir.mkdir(parents=True)
    (ctrl_dir / "flash_controller_action.py").touch()
    (ctrl_dir / "usb_vbus_test.py").touch()
    (ctrl_dir / "helper.py").touch()

    entries = await browse_test_path(repo, "tests/200_controller")

    names = [e.name for e in entries]
    assert "flash_controller_action.py" in names
    assert "usb_vbus_test.py" in names
    assert "helper.py" not in names


@pytest.mark.asyncio
async def test_browse_rejects_path_traversal(tmp_path: Path) -> None:
    repo = _make_browse_repo(tmp_path)
    (repo / "tests").mkdir()

    with pytest.raises(ValueError, match="traversal"):
        await browse_test_path(repo, "..")


@pytest.mark.asyncio
async def test_browse_rejects_path_escape(tmp_path: Path) -> None:
    repo = _make_browse_repo(tmp_path)
    (repo / "tests").mkdir()

    # A path that resolves outside the tests/ directory
    with pytest.raises(ValueError):
        await browse_test_path(repo, "src/something")


@pytest.mark.asyncio
async def test_browse_rejects_path_with_shared_prefix(tmp_path: Path) -> None:
    """tests_extra/ must not pass containment check despite sharing 'tests' prefix."""
    repo = _make_browse_repo(tmp_path)
    (repo / "tests").mkdir()
    tests_extra = repo / "tests_extra"
    tests_extra.mkdir()
    (tests_extra / "secret.py").touch()

    with pytest.raises(ValueError):
        await browse_test_path(repo, "tests_extra/secret.py")


@pytest.mark.asyncio
async def test_browse_nonexistent_path(tmp_path: Path) -> None:
    repo = _make_browse_repo(tmp_path)
    (repo / "tests").mkdir()

    with pytest.raises(ValueError, match="not found"):
        await browse_test_path(repo, "tests/nonexistent")


@pytest.mark.asyncio
async def test_browse_empty_directory(tmp_path: Path) -> None:
    repo = _make_browse_repo(tmp_path)
    power_dir = repo / "tests" / "100_power"
    power_dir.mkdir(parents=True)
    (power_dir / "__pycache__").mkdir()

    entries = await browse_test_path(repo, "tests/100_power")

    assert entries == []


@pytest.mark.asyncio
async def test_browse_skips_conftest(tmp_path: Path) -> None:
    repo = _make_browse_repo(tmp_path)
    power_dir = repo / "tests" / "100_power"
    power_dir.mkdir(parents=True)
    (power_dir / "conftest.py").touch()
    (power_dir / "test_foo.py").touch()

    entries = await browse_test_path(repo, "tests/100_power")

    names = [e.name for e in entries]
    assert "test_foo.py" in names
    assert "conftest.py" not in names


# --- _scan_noauto_markers tests ---


def test_scan_noauto_markers_detects_decorated_function(tmp_path: Path) -> None:
    source = tmp_path / "test_example.py"
    source.write_text(
        "import pytest\n"
        "\n"
        "@pytest.mark.noauto\n"
        "def test_manual(): pass\n"
        "\n"
        "def test_normal(): pass\n"
    )

    result = _scan_noauto_markers(source)

    assert result == {"test_manual"}


def test_scan_noauto_markers_no_noauto(tmp_path: Path) -> None:
    source = tmp_path / "test_example.py"
    source.write_text("def test_normal(): pass\n")

    result = _scan_noauto_markers(source)

    assert result == set()


def test_scan_noauto_markers_multiple_decorators(tmp_path: Path) -> None:
    source = tmp_path / "test_example.py"
    source.write_text(
        "import pytest\n"
        "\n"
        "@pytest.mark.slow\n"
        "@pytest.mark.noauto\n"
        "def test_slow_manual(): pass\n"
    )

    result = _scan_noauto_markers(source)

    assert "test_slow_manual" in result


def test_scan_noauto_markers_syntax_error_returns_empty(tmp_path: Path) -> None:
    source = tmp_path / "test_bad.py"
    source.write_text("def broken(:\n")

    result = _scan_noauto_markers(source)

    assert result == set()


def test_scan_noauto_markers_missing_file_returns_empty(tmp_path: Path) -> None:
    result = _scan_noauto_markers(tmp_path / "does_not_exist.py")

    assert result == set()


def test_scan_noauto_markers_detects_async_function(tmp_path: Path) -> None:
    source = tmp_path / "test_example.py"
    source.write_text(
        "import pytest\n"
        "\n"
        "@pytest.mark.noauto\n"
        "async def test_async_manual(): pass\n"
    )

    result = _scan_noauto_markers(source)

    assert "test_async_manual" in result


def test_scan_noauto_markers_ignores_module_level_pytestmark(tmp_path: Path) -> None:
    source = tmp_path / "test_example.py"
    source.write_text(
        "import pytest\n"
        "pytestmark = [pytest.mark.noauto]\n"
        "\n"
        "def test_something(): pass\n"
    )

    # Module-level pytestmark is out of scope — should NOT detect test_something
    result = _scan_noauto_markers(source)

    assert result == set()


def test_scan_noauto_markers_detects_call_form(tmp_path: Path) -> None:
    """@pytest.mark.noauto("reason") call form should also be detected."""
    source = tmp_path / "test_example.py"
    source.write_text(
        "import pytest\n"
        "\n"
        '@pytest.mark.noauto("requires manual setup")\n'
        "def test_with_reason(): pass\n"
    )

    result = _scan_noauto_markers(source)

    assert "test_with_reason" in result


# --- _collect_test_functions marker assignment tests ---


@pytest.mark.asyncio
async def test_collect_test_functions_sets_noauto_marker(tmp_path: Path) -> None:
    """Verify _collect_test_functions propagates noauto markers to BrowseEntry objects."""
    repo = tmp_path / "repo"
    power_dir = repo / "tests" / "100_power"
    power_dir.mkdir(parents=True)
    test_file = power_dir / "test_manual.py"
    test_file.write_text(
        "import pytest\n\n@pytest.mark.noauto\ndef test_noauto_fn(): pass\n"
    )

    rel_path = "tests/100_power/test_manual.py"
    fake_nodeid = f"{rel_path}::test_noauto_fn"
    fake_entries = [BrowseEntry(name="test_noauto_fn", type="function", path=fake_nodeid)]

    with patch("halspa_runner.test_discovery._run_collect", new=AsyncMock(return_value=fake_entries)):
        entries = await browse_test_path(repo, rel_path)

    assert len(entries) == 1
    assert entries[0].markers == ["noauto"]


@pytest.mark.asyncio
async def test_collect_test_functions_no_marker_for_normal_fn(tmp_path: Path) -> None:
    """Normal functions get no noauto marker even when browsed at file level."""
    repo = tmp_path / "repo"
    power_dir = repo / "tests" / "100_power"
    power_dir.mkdir(parents=True)
    test_file = power_dir / "test_normal.py"
    test_file.write_text("def test_normal_fn(): pass\n")

    rel_path = "tests/100_power/test_normal.py"
    fake_nodeid = f"{rel_path}::test_normal_fn"
    fake_entries = [BrowseEntry(name="test_normal_fn", type="function", path=fake_nodeid)]

    with patch("halspa_runner.test_discovery._run_collect", new=AsyncMock(return_value=fake_entries)):
        entries = await browse_test_path(repo, rel_path)

    assert len(entries) == 1
    assert entries[0].markers == []


# --- _run_collect error path tests ---


@pytest.mark.asyncio
async def test_run_collect_nonzero_exit_returns_empty(tmp_path: Path) -> None:
    """_collect_test_functions returns empty list when pytest exits non-zero."""
    repo = tmp_path / "repo"
    power_dir = repo / "tests" / "100_power"
    power_dir.mkdir(parents=True)
    test_file = power_dir / "test_bad.py"
    test_file.write_text("def test_fn(): pass\n")

    rel_path = "tests/100_power/test_bad.py"

    proc_mock = AsyncMock()
    proc_mock.returncode = 1
    proc_mock.communicate = AsyncMock(return_value=(b"", b"collection error"))

    with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
        entries = await browse_test_path(repo, rel_path)

    assert entries == []
