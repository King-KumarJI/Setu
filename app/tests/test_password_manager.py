import pytest

from app.core.models import DBMS, DetectionStatus, Installation, OperationResult
from app.core.password_manager import (
    PasswordChangeRequest,
    ValidationError,
    change_password,
    validate,
)
from app.databases.base import DatabaseAdapter

INSTALLATION = Installation(dbms=DBMS.MYSQL, status=DetectionStatus.SERVER_RUNNING)


def test_validate_rejects_empty_password():
    request = PasswordChangeRequest(INSTALLATION, "", "")
    with pytest.raises(ValidationError):
        validate(request)


def test_validate_rejects_mismatched_passwords():
    request = PasswordChangeRequest(INSTALLATION, "abc123", "abc124")
    with pytest.raises(ValidationError):
        validate(request)


def test_validate_accepts_matching_passwords():
    request = PasswordChangeRequest(INSTALLATION, "abc123", "abc123")
    validate(request)  # should not raise


class _FakeAdapter(DatabaseAdapter):
    dbms = DBMS.MYSQL

    def detect(self):
        raise NotImplementedError

    def get_installations(self):
        raise NotImplementedError

    def get_version(self, installation):
        raise NotImplementedError

    def change_password(self, installation, new_password):
        return OperationResult(success=True, verified=False, message="changed")

    def verify(self, installation, password):
        return True


def test_change_password_verifies_when_adapter_did_not():
    adapter = _FakeAdapter()
    request = PasswordChangeRequest(INSTALLATION, "abc123", "abc123")
    result = change_password(adapter, request)
    assert result.success
    assert result.verified
