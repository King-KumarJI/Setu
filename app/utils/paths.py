"""
Path discovery utilities.

Rule 6 (no hardcoded user paths): helpers here return *candidate*
locations derived from environment variables and OS conventions,
never a single hardcoded path treated as ground truth. Detection
logic (Phase 1) treats these as one signal among several, never as
proof by themselves (Rule 5).
"""
from __future__ import annotations

import os
from pathlib import Path


def program_files_dirs() -> list[Path]:
    """Return the Program Files-style directories that exist on this machine.

    Uses environment variables rather than hardcoded drive letters, so
    this works on non-C: installs and localized Windows editions.
    """
    candidates: list[Path] = []
    for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        value = os.environ.get(var)
        if value:
            candidates.append(Path(value))

    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        if path not in seen and path.exists():
            seen.add(path)
            unique.append(path)
    return unique


def path_entries() -> list[Path]:
    """Return the directories on the current PATH that actually exist."""
    raw = os.environ.get("PATH", "")
    entries: list[Path] = []
    for part in raw.split(os.pathsep):
        if not part:
            continue
        path = Path(part)
        if path.exists():
            entries.append(path)
    return entries


def app_data_dir(app_name: str = "Setu") -> Path:
    """Return this app's local-appdata directory (created if needed).

    Used for logs and other non-secret local state -- never for
    passwords (Rule 4).
    """
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    directory = Path(base) / app_name
    directory.mkdir(parents=True, exist_ok=True)
    return directory
