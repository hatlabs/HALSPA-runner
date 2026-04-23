"""Scan a directory for *-tests repositories and enumerate test categories."""

import asyncio
import fnmatch
import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .subprocess_utils import find_uv

logger = logging.getLogger(__name__)

_COLLECT_TIMEOUT = 5.0

# Default pytest test file patterns (same as pytest's defaults)
_DEFAULT_PYTHON_FILES = ["test_*.py", "*_test.py"]

_SKIP_NAMES = {"__pycache__", "__init__.py", "conftest.py"}


@dataclass
class Category:
    """A numbered test category directory within a test repository."""

    name: str
    path: Path


@dataclass
class BrowseEntry:
    """An item in a browsed test directory."""

    name: str
    type: str  # "directory" | "file" | "function"
    path: str  # relative to repo root


@dataclass
class DUT:
    """A discovered device-under-test with its test categories."""

    name: str
    path: Path
    categories: list[Category] = field(default_factory=list)


class BrowseError(Exception):
    """Raised when browsing fails due to a system error (not user input)."""


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


def _read_python_files(repo_path: Path) -> list[str]:
    """Read python_files patterns from repo's pyproject.toml.

    Falls back to pytest defaults if pyproject.toml is missing or
    doesn't configure python_files.
    """
    pyproject = repo_path / "pyproject.toml"
    if not pyproject.is_file():
        return _DEFAULT_PYTHON_FILES

    try:
        with open(pyproject, "rb") as f:
            config = tomllib.load(f)
        patterns = config.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("python_files")
        if patterns and isinstance(patterns, list):
            return patterns
    except (tomllib.TOMLDecodeError, OSError) as e:
        logger.warning("Failed to read pyproject.toml at %s: %s", pyproject, e)

    return _DEFAULT_PYTHON_FILES


def _is_test_file(name: str, patterns: list[str]) -> bool:
    """Check if a filename matches any of the given pytest file patterns."""
    return name.endswith(".py") and any(fnmatch.fnmatch(name, p) for p in patterns)


async def browse_test_path(repo_path: Path, relative_path: str) -> list[BrowseEntry]:
    """Browse contents of a path within a DUT's test directory.

    For directories, returns subdirectories and test files.
    For .py test files, returns test function names via pytest --collect-only.

    Args:
        repo_path: Root of the *-tests repository.
        relative_path: Path relative to repo root (e.g., "tests/100_power")
                       or empty string for tests/ root.

    Returns:
        Sorted list of browse entries.

    Raises:
        ValueError: If path is invalid or escapes the repo.
        BrowseError: If browsing fails due to a system error.
    """
    if ".." in relative_path.split("/"):
        raise ValueError("Path traversal not allowed")

    tests_dir = repo_path / "tests"
    if relative_path:
        target = (repo_path / relative_path).resolve()
    else:
        target = tests_dir.resolve()

    # Containment check using proper path semantics
    try:
        target.relative_to(tests_dir.resolve())
    except ValueError:
        raise ValueError("Path escapes test directory")

    if not target.exists():
        raise ValueError(f"Path not found: {relative_path}")

    patterns = _read_python_files(repo_path)

    if target.is_file() and _is_test_file(target.name, patterns):
        return await _collect_test_functions(repo_path, target)

    if not target.is_dir():
        raise ValueError(f"Not a directory or test file: {relative_path}")

    return _browse_directory(repo_path, target, patterns)


def _browse_directory(
    repo_path: Path, directory: Path, patterns: list[str],
) -> list[BrowseEntry]:
    """List test-relevant entries in a directory using filesystem scan."""
    entries: list[BrowseEntry] = []

    try:
        items = sorted(directory.iterdir())
    except OSError as e:
        raise BrowseError(f"Cannot list directory {directory}: {e}") from e

    for item in items:
        if item.name in _SKIP_NAMES:
            continue

        rel_path = str(item.relative_to(repo_path))

        if item.is_dir():
            if _dir_has_tests(item, patterns):
                entries.append(BrowseEntry(name=item.name, type="directory", path=rel_path))
        elif _is_test_file(item.name, patterns):
            entries.append(BrowseEntry(name=item.name, type="file", path=rel_path))

    return entries


def _dir_has_tests(directory: Path, patterns: list[str]) -> bool:
    """Check if a directory or its descendants contain test files."""
    try:
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if d not in _SKIP_NAMES]
            for f in files:
                if _is_test_file(f, patterns):
                    return True
    except OSError as e:
        logger.warning("Cannot walk directory %s: %s", directory, e)
    return False


async def _collect_test_functions(repo_path: Path, test_file: Path) -> list[BrowseEntry]:
    """Discover test functions in a file using pytest --collect-only."""
    uv = find_uv()
    rel_file = str(test_file.relative_to(repo_path))

    try:
        return await _run_collect(uv, rel_file, repo_path)
    except Exception:
        logger.warning("pytest --collect-only failed for %s", rel_file, exc_info=True)
        return []


async def _run_collect(uv: str, rel_file: str, repo_path: Path) -> list[BrowseEntry]:
    """Run pytest --collect-only and parse output."""
    # Clear VIRTUAL_ENV so uv discovers the target repo's project, not ours
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    proc = await asyncio.create_subprocess_exec(
        uv, "run", "pytest", "--collect-only", "-qq", rel_file,
        cwd=str(repo_path),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_COLLECT_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        logger.warning("pytest --collect-only timed out for %s", rel_file)
        return []

    if proc.returncode != 0:
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        logger.warning(
            "pytest --collect-only returned %d for %s: %s",
            proc.returncode, rel_file, stderr_text or "(no stderr)",
        )
        return []

    entries: list[BrowseEntry] = []
    seen: set[str] = set()

    for line in stdout.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        # pytest -qq output: "tests/100_power/test_rails.py::test_5v_output"
        if "::" not in line or not line.startswith(rel_file):
            continue

        nodeid = line
        # Extract function name (last :: segment)
        func_name = nodeid.rsplit("::", 1)[-1]

        if nodeid not in seen:
            seen.add(nodeid)
            entries.append(BrowseEntry(name=func_name, type="function", path=nodeid))

    return entries
