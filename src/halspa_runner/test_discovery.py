"""Scan a directory for *-tests repositories and enumerate test categories."""

from dataclasses import dataclass, field
from pathlib import Path

from . import config


@dataclass
class Category:
    """A numbered test category directory within a test repository."""

    name: str
    path: Path


@dataclass
class DUT:
    """A discovered device-under-test with its test categories."""

    name: str
    path: Path
    categories: list[Category] = field(default_factory=list)


def discover_duts(scan_dir: Path | None = None) -> list[DUT]:
    """Scan a directory for *-tests repos and return discovered DUTs.

    Each *-tests directory must have a tests/ subdirectory containing at least
    one numbered directory (e.g., 000_selftest, 100_power) to be considered valid.

    Args:
        scan_dir: Directory to scan. Defaults to config.TEST_DIR.

    Returns:
        Sorted list of discovered DUTs.
    """
    if scan_dir is None:
        scan_dir = config.TEST_DIR

    scan_dir = Path(scan_dir)
    if not scan_dir.is_dir():
        return []

    duts: list[DUT] = []

    for entry in sorted(scan_dir.iterdir()):
        # Follow symlinks — resolve to check if it's a directory
        if not entry.name.endswith("-tests"):
            continue
        # Resolve symlinks for is_dir check
        resolved = entry.resolve()
        if not resolved.is_dir():
            continue

        tests_dir = resolved / "tests"
        if not tests_dir.is_dir():
            continue

        categories = _enumerate_categories(tests_dir)
        if not categories:
            continue

        dut_name = entry.name.removesuffix("-tests").upper()
        duts.append(DUT(name=dut_name, path=resolved, categories=categories))

    return duts


def _enumerate_categories(tests_dir: Path) -> list[Category]:
    """List numbered test category directories, sorted by name."""
    categories: list[Category] = []

    for entry in sorted(tests_dir.iterdir()):
        if not entry.is_dir():
            continue
        # Must start with a digit (numbered directory convention)
        if not entry.name[0:1].isdigit():
            continue
        categories.append(Category(name=entry.name, path=entry))

    return categories
