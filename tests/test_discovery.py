"""Tests for test_discovery module."""

from pathlib import Path

from halspa_runner.test_discovery import DUT, Category, discover_duts


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
