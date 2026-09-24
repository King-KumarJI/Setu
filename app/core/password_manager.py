"""
Password change orchestration (validation + adapter dispatch).

The GUI calls only this module -- it never talks to a database
adapter directly, and this module contains no DBMS-specific logic
(Rule 7 / Rule 8).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.models import Installation, OperationResult
from app.core.verifier import verify_password
from app.databases.base import DatabaseAdapter
from app.utils.logging import get_logger, register_secret

logger = get_logger(__name__)


class ValidationError(Exception):
    """Raised when the requested password change fails input validation."""


@dataclass
class PasswordChangeRequest:
    installation: Installation
    new_password: str
    confirm_password: str


def validate(request: PasswordChangeRequest) -> None:
    """Reject empty or mismatched password fields (FR-05).

    Raises ValidationError with a user-facing message; never logs the
    password values themselves.
    """
    if not request.new_password or not request.confirm_password:
        raise ValidationError("Enter and confirm the new password.")
    if request.new_password != request.confirm_password:
        raise ValidationError("Passwords do not match.")


def change_password(
    adapter: DatabaseAdapter, request: PasswordChangeRequest
) -> OperationResult:
    """Validate, dispatch to the adapter, and verify the result if needed.

    This is the only place orchestration logic lives; adapters do the
    DBMS-specific work, never this function.
    """
    validate(request)
    register_secret(request.new_password)

    logger.info("Starting password change for %s installation.", adapter.dbms)

    result = adapter.change_password(request.installation, request.new_password)

    if result.success and not result.verified:
        verified = verify_password(adapter, request.installation, request.new_password)
        result = OperationResult(
            success=result.success,
            verified=verified,
            message=result.message,
            restored_configuration=result.restored_configuration,
        )

    logger.info(
        "Password change for %s finished: success=%s verified=%s",
        adapter.dbms,
        result.success,
        result.verified,
    )
    return result
