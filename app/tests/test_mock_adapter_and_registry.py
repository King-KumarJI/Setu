from app.core.adapters_registry import ADAPTER_CLASSES, get_adapter
from app.core.models import DBMS, DetectionStatus
from app.core.password_manager import PasswordChangeRequest, change_password
from app.databases.mock import MockAdapter


def test_registry_covers_every_dbms():
    assert set(ADAPTER_CLASSES.keys()) == set(DBMS)


def test_get_adapter_returns_correct_dbms():
    for dbms in DBMS:
        adapter = get_adapter(dbms)
        assert adapter.dbms == dbms


def test_mock_adapter_detects_a_running_installation():
    adapter = MockAdapter(DBMS.MONGODB)
    result = adapter.detect()
    assert result.status == DetectionStatus.SERVER_RUNNING
    assert not result.has_multiple_installations


def test_mock_adapter_satisfies_full_password_change_flow():
    adapter = MockAdapter(DBMS.MONGODB)
    installation = adapter.get_installations()[0]
    request = PasswordChangeRequest(
        installation=installation, new_password="abc123", confirm_password="abc123"
    )
    result = change_password(adapter, request)
    assert result.success
    assert result.verified
