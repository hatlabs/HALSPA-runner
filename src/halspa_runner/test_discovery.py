"""Scan a directory for *-tests repositories and enumerate test categories."""

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import config

logger = logging.getLogger(__name__)

_COLLECT_TIMEOUT = 5.0


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


async def browse_test_path(repo_path: Path, relative_path: str) -> list[BrowseEntry]:
    """Browse contents of a path within a DUT's test directory.

    For directories, returns subdirectories and test files (via pytest collection).
    For .py files, returns test function names via pytest --collect-only.

    Args:
        repo_path: Root of the *-tests repository.
        relative_path: Path relative to repo root (e.g., "tests/100_power")
                       or empty string for tests/ root.

    Returns:
        Sorted list of browse entries.

    Raises:
        ValueError: If path is invalid or escapes the repo.
    """
    if ".." in relative_path.split("/"):
        raise ValueError("Path traversal not allowed")

    tests_dir = repo_path / "tests"
    if relative_path:
        target = (repo_path / relative_path).resolve()
    else:
        target = tests_dir.resolve()

    # Containment check
    if not str(target).startswith(str(tests_dir.resolve())):
        raise ValueError("Path escapes test directory")

    if not target.exists():
        raise ValueError(f"Path not found: {relative_path}")

    if target.is_file() and target.suffix == ".py":
        return await _collect_test_functions(repo_path, target)

    if not target.is_dir():
        raise ValueError(f"Not a directory or test file: {relative_path}")

    return await _browse_directory(repo_path, target)


async def _browse_directory(repo_path: Path, directory: Path) -> list[BrowseEntry]:
    """List test files and subdirectories using pytest collection."""
    rel_dir = str(directory.relative_to(repo_path))
    uv = _find_uv()

    try:
        collected = await _run_collect(uv, rel_dir, repo_path)
    except Exception:
        logger.warning("pytest --collect-only failed for %s", rel_dir, exc_info=True)
        return []

    # Extract unique files and subdirectories from function-level entries
    files: dict[str, str] = {}  # name -> rel_path
    subdirs: dict[str, str] = {}  # name -> rel_path
    dir_rel = Path(rel_dir)

    for entry in collected:
        file_path_str = entry.path.split("::")[0]
        file_path = Path(file_path_str)
        file_parent = file_path.parent

        if file_parent == dir_rel:
            if file_path.name not in files:
                files[file_path.name] = file_path_str
        else:
            try:
                relative = file_parent.relative_to(dir_rel)
                subdir_name = relative.parts[0]
                subdir_path = str(dir_rel / subdir_name)
                if subdir_name not in subdirs:
                    subdirs[subdir_name] = subdir_path
            except ValueError:
                continue

    entries: list[BrowseEntry] = []
    for name in sorted(subdirs):
        entries.append(BrowseEntry(name=name, type="directory", path=subdirs[name]))
    for name in sorted(files):
        entries.append(BrowseEntry(name=name, type="file", path=files[name]))

    return entries


def _find_uv() -> str:
    """Locate the uv binary."""
    uv = shutil.which("uv")
    if not uv:
        for candidate in [
            Path.home() / ".local" / "bin" / "uv",
            Path("/usr/local/bin/uv"),
        ]:
            if candidate.exists():
                uv = str(candidate)
                break
    return uv or "uv"


async def _collect_test_functions(repo_path: Path, test_file: Path) -> list[BrowseEntry]:
    """Discover test functions in a file using pytest --collect-only."""
    uv = _find_uv()
    rel_file = str(test_file.relative_to(repo_path))

    try:
        return await _run_collect(uv, rel_file, repo_path)
    except Exception:
        logger.warning("pytest --collect-only failed for %s", rel_file, exc_info=True)
        return []


async def _run_collect(uv: str, rel_file: str, repo_path: Path) -> list[BrowseEntry]:
    """Run pytest --collect-only and parse output."""
    # Clear VIRTUAL_ENV so uv discovers the target repo's project, not ours.
    # Add repo root to PYTHONPATH so test modules can import repo-level config
    # (e.g., dut_config.py) even with --noconftest.
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    existing_pypath = env.get("PYTHONPATH", "")
    repo_str = str(repo_path)
    env["PYTHONPATH"] = f"{repo_str}:{existing_pypath}" if existing_pypath else repo_str
    proc = await asyncio.create_subprocess_exec(
        uv, "run", "pytest", "--collect-only", "-qq", "--noconftest", rel_file,
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

    if proc.returncode not in (0, 2):
        # 0=success, 2=partial collection (some import errors) — both have usable output.
        # Other codes (3=internal error, 4=nothing collected, 5=nothing selected) don't.
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
        # pytest -q output: "tests/100_power/test_rails.py::test_5v_output"
        if "::" not in line or not line.startswith(rel_file):
            continue

        nodeid = line
        # Extract function name (last :: segment)
        func_name = nodeid.rsplit("::", 1)[-1]

        if nodeid not in seen:
            seen.add(nodeid)
            entries.append(BrowseEntry(name=func_name, type="function", path=nodeid))

    return entries
