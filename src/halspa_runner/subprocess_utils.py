"""Shared subprocess utilities."""

import shutil
from pathlib import Path


def find_uv() -> str:
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
