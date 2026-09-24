import os
import stat
import sys

from app.core.models import DBMS, DetectionStatus, Installation
from app.databases.postgresql import PostgreSQLAdapter, _pgpass_escape


def _assert_owner_only_permissions(path):
    """See the identical helper and rationale in test_mysql_adapter.py."""
    if sys.platform == "win32":
        assert os.access(path, os.W_OK)
    else:
        assert stat.S_IMODE(path.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR


class _FakeServiceManager:
    def __init__(self, initial_state="RUNNING", binary_path=None):
        self.state = initial_state
        self.binary_path = binary_path
        self.start_calls = []
        self.start_should_succeed = True

    def get_service_state(self, name):
        return self.state

    def start_service(self, name, timeout=30):
        self.start_calls.append(name)
        if self.start_should_succeed:
            self.state = "RUNNING"
        return self.start_should_succeed

    def get_service_binary_path(self, name):
        return self.binary_path


def _installation(tmp_path, service_name="postgresql-x64-16"):
    server_exe = tmp_path / "postgres"
    server_exe.touch()
    (tmp_path / "pg_ctl").touch()
    (tmp_path / "psql").touch()
    return Installation(
        dbms=DBMS.POSTGRESQL,
        status=DetectionStatus.SERVER_RUNNING,
        version="16.1",
        executable_path=str(server_exe),
        service_name=service_name,
    )


def _make_datadir(tmp_path, hba_content="host all all 0.0.0.0/0 md5\n", conf_content=""):
    datadir = tmp_path / "data"
    datadir.mkdir()
    (datadir / "pg_hba.conf").write_text(hba_content)
    if conf_content:
        (datadir / "postgresql.conf").write_text(conf_content)
    return datadir


def _adapter_with_mocks(service_manager=None, reload_ok=True, alter_ok=True):
    adapter = PostgreSQLAdapter(service_manager=service_manager or _FakeServiceManager())
    adapter._reload = lambda pg_ctl, datadir: reload_ok
    adapter._apply_new_password = lambda psql, port, pw: alter_ok
    return adapter


# ----------------------------------------------------------------------
# Discovery helpers
# ----------------------------------------------------------------------
def test_resolve_datadir_from_pgdata_env(tmp_path, monkeypatch):
    datadir = tmp_path / "pgdata"
    datadir.mkdir()
    monkeypatch.setenv("PGDATA", str(datadir))
    adapter = PostgreSQLAdapter(service_manager=_FakeServiceManager())
    assert adapter._resolve_datadir(_installation(tmp_path)) == datadir


def test_resolve_datadir_from_service_binary_path(tmp_path, monkeypatch):
    monkeypatch.delenv("PGDATA", raising=False)
    datadir = tmp_path / "data"
    datadir.mkdir()
    binary_path = (
        f'"C:\\PostgreSQL\\16\\bin\\pg_ctl.exe" runservice -N "postgresql-x64-16" '
        f'-D "{datadir}" -w'
    )
    adapter = PostgreSQLAdapter(service_manager=_FakeServiceManager(binary_path=binary_path))
    assert adapter._resolve_datadir(_installation(tmp_path)) == datadir


def test_resolve_datadir_returns_none_when_nothing_available(tmp_path, monkeypatch):
    monkeypatch.delenv("PGDATA", raising=False)
    adapter = PostgreSQLAdapter(service_manager=_FakeServiceManager(binary_path=None))
    assert adapter._resolve_datadir(_installation(tmp_path)) is None


def test_resolve_port_parses_config(tmp_path):
    datadir = _make_datadir(tmp_path, conf_content="listen_addresses = '*'\nport = 5433\n")
    assert PostgreSQLAdapter()._resolve_port(datadir) == 5433


def test_resolve_port_defaults_when_commented_or_missing(tmp_path):
    datadir = _make_datadir(tmp_path, conf_content="#port = 5432\n")
    assert PostgreSQLAdapter()._resolve_port(datadir) == 5432


def test_pgpass_escape_handles_colons_and_backslashes():
    assert _pgpass_escape("pa:ss\\word") == "pa\\:ss\\\\word"


def test_write_pgpass_file_contents_and_permissions():
    path = PostgreSQLAdapter._write_pgpass_file("127.0.0.1", 5432, "se:cret")
    try:
        assert path.read_text() == "127.0.0.1:5432:*:postgres:se\\:cret\n"
        _assert_owner_only_permissions(path)
    finally:
        path.unlink(missing_ok=True)


# ----------------------------------------------------------------------
# pg_hba.conf write/restore mechanics
# ----------------------------------------------------------------------
def test_write_and_restore_trust_rule_round_trips(tmp_path):
    datadir = _make_datadir(tmp_path)
    hba_path = datadir / "pg_hba.conf"
    original = hba_path.read_text()

    adapter = PostgreSQLAdapter()
    adapter._reload = lambda pg_ctl, dd: True

    adapter._write_trust_rule(hba_path, original)
    written = hba_path.read_text()
    assert "trust" in written
    assert written.endswith(original)
    assert written != original

    restored = adapter._restore_hba(hba_path, original, tmp_path / "pg_ctl", datadir)
    assert restored is True
    assert hba_path.read_text() == original


def test_restore_hba_returns_false_when_write_fails(tmp_path):
    datadir = _make_datadir(tmp_path)
    hba_path = datadir / "pg_hba.conf"
    original = hba_path.read_text()
    adapter = PostgreSQLAdapter()
    adapter._reload = lambda pg_ctl, dd: True

    hba_path.chmod(stat.S_IREAD)
    try:
        assert adapter._restore_hba(hba_path, original, tmp_path / "pg_ctl", datadir) is False
    finally:
        hba_path.chmod(stat.S_IRUSR | stat.S_IWUSR)


# ----------------------------------------------------------------------
# change_password orchestration
# ----------------------------------------------------------------------
def test_change_password_refuses_client_only_installation():
    adapter = PostgreSQLAdapter()
    installation = Installation(dbms=DBMS.POSTGRESQL, status=DetectionStatus.EXECUTABLE_FOUND)
    result = adapter.change_password(installation, "newpass123")
    assert not result.success
    assert "client was detected" in result.message


def test_change_password_refuses_when_no_executable_path():
    adapter = PostgreSQLAdapter()
    installation = Installation(dbms=DBMS.POSTGRESQL, status=DetectionStatus.SERVER_RUNNING)
    result = adapter.change_password(installation, "newpass123")
    assert not result.success
    assert "No PostgreSQL server executable path" in result.message


def test_change_password_refuses_when_datadir_unresolved(tmp_path, monkeypatch):
    monkeypatch.delenv("PGDATA", raising=False)
    adapter = PostgreSQLAdapter(service_manager=_FakeServiceManager(binary_path=None))
    result = adapter.change_password(_installation(tmp_path), "newpass123")
    assert not result.success
    assert "data directory" in result.message


def test_change_password_refuses_when_hba_missing(tmp_path, monkeypatch):
    datadir = tmp_path / "data"
    datadir.mkdir()
    monkeypatch.setenv("PGDATA", str(datadir))
    adapter = PostgreSQLAdapter(service_manager=_FakeServiceManager())
    result = adapter.change_password(_installation(tmp_path), "newpass123")
    assert not result.success
    assert "Expected configuration file not found" in result.message


def test_change_password_starts_stopped_service_before_reload(tmp_path, monkeypatch):
    datadir = _make_datadir(tmp_path)
    monkeypatch.setenv("PGDATA", str(datadir))
    fake_service = _FakeServiceManager(initial_state="STOPPED")
    adapter = _adapter_with_mocks(service_manager=fake_service)

    result = adapter.change_password(_installation(tmp_path), "newpass123")

    assert fake_service.start_calls == ["postgresql-x64-16"]
    assert result.success


def test_change_password_aborts_if_service_will_not_start(tmp_path, monkeypatch):
    datadir = _make_datadir(tmp_path)
    monkeypatch.setenv("PGDATA", str(datadir))
    fake_service = _FakeServiceManager(initial_state="STOPPED")
    fake_service.start_should_succeed = False
    adapter = _adapter_with_mocks(service_manager=fake_service)

    result = adapter.change_password(_installation(tmp_path), "newpass123")

    assert not result.success
    assert "Could not start" in result.message


def test_change_password_full_success_restores_hba(tmp_path, monkeypatch):
    original_content = "host all all 0.0.0.0/0 md5\n"
    datadir = _make_datadir(tmp_path, hba_content=original_content)
    monkeypatch.setenv("PGDATA", str(datadir))
    adapter = _adapter_with_mocks()

    result = adapter.change_password(_installation(tmp_path), "newpass123")

    assert result.success
    assert result.restored_configuration is True
    assert (datadir / "pg_hba.conf").read_text() == original_content


def test_change_password_reload_failure_still_restores_hba(tmp_path, monkeypatch):
    original_content = "host all all 0.0.0.0/0 md5\n"
    datadir = _make_datadir(tmp_path, hba_content=original_content)
    monkeypatch.setenv("PGDATA", str(datadir))
    adapter = _adapter_with_mocks(reload_ok=False)

    result = adapter.change_password(_installation(tmp_path), "newpass123")

    assert not result.success
    assert result.restored_configuration is True
    assert (datadir / "pg_hba.conf").read_text() == original_content


def test_change_password_alter_failure_still_restores_hba(tmp_path, monkeypatch):
    original_content = "host all all 0.0.0.0/0 md5\n"
    datadir = _make_datadir(tmp_path, hba_content=original_content)
    monkeypatch.setenv("PGDATA", str(datadir))
    adapter = _adapter_with_mocks(alter_ok=False)

    result = adapter.change_password(_installation(tmp_path), "newpass123")

    assert not result.success
    assert result.restored_configuration is True
    assert (datadir / "pg_hba.conf").read_text() == original_content
    assert "IMPORTANT" not in result.message


def test_change_password_warns_loudly_when_restoration_cannot_be_confirmed(tmp_path, monkeypatch):
    datadir = _make_datadir(tmp_path)
    monkeypatch.setenv("PGDATA", str(datadir))
    adapter = _adapter_with_mocks()
    monkeypatch.setattr(adapter, "_restore_hba", lambda *a, **k: False)

    result = adapter.change_password(_installation(tmp_path), "newpass123")

    assert result.success
    assert result.restored_configuration is False
    assert "IMPORTANT" in result.message or "could not be confirmed removed" in result.message
