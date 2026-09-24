"""
Presentation logic for the main window.

Kept free of any GUI toolkit import so it can be unit tested without
PySide6 installed and without a display -- main_window.py is the
only place in this app that touches Qt, and it calls into these pure
functions rather than formatting status/error text inline.
"""
from __future__ import annotations

from app.core.models import DBMS, DetectionResult, DetectionStatus, Installation
from app.utils.logging import redact

CHECK = "✓"  # check mark
WARNING = "⚠"  # warning sign
CROSS = "✕"  # multiplication x, used as a plain "not detected" mark


def friendly_error(exc: Exception) -> str:
    """Translate an exception into user-facing text.

    Never a raw traceback (02-design.md section 7: "Avoid raw
    tracebacks"). NotImplementedError gets its own wording because,
    right now, every adapter except the mock one *is* unimplemented
    (Phase 3+ builds them) -- that is an expected, explainable state,
    not a bug.
    """
    if isinstance(exc, NotImplementedError):
        return (
            "This database isn't supported yet. Detection and password-change "
            "logic for it hasn't been built into Setu yet."
        )
    # Nothing in this codebase is known to raise a secret-bearing
    # exception (Rule 3), but this is defense in depth for whatever
    # gets raised next -- a password on screen is one screenshot away
    # from leaking further than the person who typed it.
    return redact(f"Something went wrong: {exc}")


def status_text(dbms: DBMS, result: DetectionResult | None) -> str:
    """Build the status-area text for one DBMS's detection result.

    Matches the three core states from 02-design.md section 3
    (detected / client-only / not detected), plus a multiple-
    installations note. Status is conveyed with a symbol and words
    together, never color alone (02-design.md section 8:
    accessibility).
    """
    name = str(dbms)
    if result is None or result.status == DetectionStatus.NOT_DETECTED:
        return f"{CROSS} {name} not detected"

    if result.status == DetectionStatus.EXECUTABLE_FOUND:
        text = f"{WARNING} {name} executable detected\nServer status could not be confirmed"
    elif result.status == DetectionStatus.SERVER_FOUND:
        text = f"{WARNING} {name} detected\nServer status could not be confirmed running"
    else:
        version = result.installations[0].version if result.installations else None
        version_line = f"\nVersion: {version}" if version else ""
        text = f"{CHECK} {name} detected{version_line}\nServer: Running"

    if result.has_multiple_installations:
        text += "\n\nMultiple installations detected — choose one below."
    return text


def default_installation(
    dbms: DBMS, results: dict[DBMS, DetectionResult]
) -> Installation | None:
    """The installation to act on when the user hasn't explicitly picked one
    from a multiple-installations list -- the first one detected.

    Returning None (rather than guessing) when nothing was detected is
    what lets the caller refuse the operation instead of silently
    proceeding (FR-04 / Rule 25: when uncertain, stop).
    """
    result = results.get(dbms)
    if result and result.installations:
        return result.installations[0]
    return None


def operation_result_text(success: bool, verified: bool, message: str) -> str:
    """Status text for a finished password-change operation.

    `verified` is kept distinct from `success` in the wording itself
    (Rule 17) -- a success that could not be verified must never read
    the same as a confirmed success, and must never read as a plain
    failure either.
    """
    if success and verified:
        return redact(f"{CHECK} Password changed and verified.\n{message}")
    if success and not verified:
        return redact(
            f"{WARNING} The password change appears to have succeeded, but it "
            f"could not be verified.\n{message}"
        )
    return redact(f"{CROSS} Password change failed.\n{message}")
