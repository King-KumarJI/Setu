"""
Post-change credential verification.

Centralizing this call (rather than having callers invoke
`adapter.verify` directly) gives one place to add consistent
timeout/retry/logging behavior later without touching every adapter.
Rule 17: never claim success without verification.
"""
from __future__ import annotations

from app.core.models import Installation
from app.databases.base import DatabaseAdapter


def verify_password(
    adapter: DatabaseAdapter, installation: Installation, password: str
) -> bool:
    """Confirm a password actually authenticates against the given installation."""
    return adapter.verify(installation, password)
