"""
Administrator-elevation detection.

Almost every operation Setu performs -- stopping/starting a Windows
service, writing into a Program Files-owned data directory or config
file -- requires the process to be running elevated (as Administrator).
Without this check, an unelevated run doesn't fail cleanly up front;
it fails confusingly partway through a password-reset attempt, at
exactly the moment Rule 11 (fail safely, never hide a failed
restoration) matters most -- e.g. a service-stop call raising an
access-denied error after a backup was already taken but before any
change was made.

This module answers one question -- "is this process elevated right
now?" -- so the GUI can tell the user up front, before they've typed a
password and clicked the button, rather than surfacing a raw
WinError partway through an operation.

Detection only; this module never attempts to elevate the process
itself (e.g. via a UAC re-launch), since that's a product decision
for the GUI layer, not something to hide inside a utility function.
"""
from __future__ import annotations

import ctypes
import logging
import sys

logger = logging.getLogger(__name__)


def is_windows() -> bool:
    """True when running on Windows -- the only platform this check
    (or the app itself, per the current phase) targets."""
    return sys.platform == "win32"


def is_elevated() -> bool | None:
    """Return whether the current process has Administrator privileges.

    Returns:
        True  -- confirmed elevated.
        False -- confirmed running as a standard (non-elevated) user.
        None  -- couldn't determine this (non-Windows, or the check
                 itself failed). Callers should treat `None` as "unknown,
                 don't block on it" rather than assuming either answer --
                 Rule 25 (when uncertain, stop rather than guess) cuts
                 against silently treating unknown as either elevated or
                 not.

    Uses ctypes.windll.shell32.IsUserAnAdmin(), the standard documented
    Windows API for this (Rule 9: no undocumented mechanism), rather
    than a heuristic like "can I write to Program Files" which can give
    a false answer depending on ACLs and virtualization.
    """
    if not is_windows():
        return None
    try:
        # IsUserAnAdmin returns a BOOL (int): nonzero means elevated.
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except (AttributeError, OSError) as exc:
        logger.warning("Could not determine elevation state: %s", type(exc).__name__)
        return None


def elevation_warning() -> str | None:
    """A user-facing message if the process is confirmedly not elevated,
    else None (either elevated, or the state is unknown/not applicable).

    Deliberately only warns on a *confirmed* False -- an unknown state
    stays silent here rather than nagging the user with a warning that
    might be wrong (see the None case in `is_elevated`).
    """
    if is_elevated() is False:
        return (
            "Setu is not running as Administrator. Detecting installed "
            "databases will still work, but changing a password usually "
            "requires stopping/starting a Windows service and may fail "
            "partway through. Close Setu and re-launch it with "
            "\"Run as administrator\" before making changes."
        )
    return None
