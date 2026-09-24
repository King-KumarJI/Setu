import os
import stat
import sys

from app.core.models import DBMS, DetectionStatus, Installation
from app.databases.mariadb import MariaDBAdapter


def _make_executable(path, output):
    """Create a fake "executable" that prints `output` verbatim to
    stdout when run with any arguments -- portable across this Linux
    development sandbox and the real Windows target (see the identical
    helper and rationale in test_detector.py)."""
    if sys.platform == "win32":
        exe_path = path.with_name(path.name + ".bat")
        lines = ["@echo off"]
        for line in output.splitlines():
            lines.append(f"echo {line}" if line else "echo.")
        exe_path.write_text("\r\n".join(lines) + "\r\n")
        return exe_path
    path.write_text(f"#!/bin/sh\ncat <<'SETU_EOF'\n{output}\nSETU_EOF\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _assert_owner_only_permissions(path):
    """See the identical helper and rationale in test_mysql_adapter.py."""
    if sys.platform == "win32":
        assert os.access(path, os.W_OK)
    else:
        assert stat.S_IMODE(path.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR


class _FakeServiceManager:
    def __init__(self, initial_state="RUNNING"):
        self.state = initial_state
        self.stop_calls = []
        self.start_calls = []
        self.stop_should_succeed = True
        self.start_should_succeed = True

    def get_service_state(self, name):
        return self.state

    def stop_service(self, name, timeout=30):
        self.stop_calls.append(name)
        if self.stop_should_succeed:
            self.state = "STOPPED"
        return self.stop_should_succeed

    def start_service(self, name, timeout=30):
        self.start_calls.append(name)
        if self.start_should_succeed:
            self.state = "RUNNING"
        return self.start_should_succeed


RUNNING_INSTALLATION = Installation(
    dbms=DBMS.MARIADB,
    status=DetectionStatus.SERVER_RUNNING,
    version="11.2.2",
    executable_path="/opt/mariadb/bin/mariadbd",
    service_name="MariaDB",
)


def test_resolve_datadir_parses_verbose_help_output(tmp_path):
    fake_datadir = tmp_path / "data"
    fake_datadir.mkdir()
    mariadbd = _make_executable(
        tmp_path / "mariadbd",
        "mariadbd  Ver 11.2.2\n"
        "Variables (--variable-name=value)\n"
        f"datadir                            {fake_datadir}",
    )
    adapter = MariaDBAdapter()
    assert adapter._resolve_datadir(mariadbd) == fake_datadir


def test_resolve_datadir_returns_none_when_path_missing(tmp_path):
    mariadbd = _make_executable(tmp_path / "mariadbd", "datadir   /no/such/directory")
    adapter = MariaDBAdapter()
    assert adapter._resolve_datadir(mariadbd) is None


def test_write_init_file_contains_escaped_alter_user_statement():
    path = MariaDBAdapter._write_init_file("it's a secret")
    try:
        content = path.read_text()
        assert "ALTER USER 'root'@'localhost'" in content
        assert "it''s a secret" in content
        _assert_owner_only_permissions(path)
    finally:
        path.unlink(missing_ok=True)


def test_locate_sibling_finds_matching_extension(tmp_path):
    mariadbd = tmp_path / "mariadbd"
    mariadbd.touch()
    admin = tmp_path / "mariadb-admin"
    admin.touch()
    installation = Installation(
        dbms=DBMS.MARIADB, status=DetectionStatus.SERVER_RUNNING, executable_path=str(mariadbd)
    )
    adapter = MariaDBAdapter()
    assert adapter._locate_sibling(installation, "mariadb-admin") == admin


def test_change_password_refuses_client_only_installation():
    adapter = MariaDBAdapter()
    installation = Installation(dbms=DBMS.MARIADB, status=DetectionStatus.EXECUTABLE_FOUND)
    result = adapter.change_password(installation, "newpass123")
    assert not result.success
    assert "client was detected" in result.message


def test_change_password_refuses_when_datadir_unresolved(monkeypatch):
    adapter = MariaDBAdapter()
    monkeypatch.setattr(adapter, "_resolve_datadir", lambda mariadbd: None)
    result = adapter.change_password(RUNNING_INSTALLATION, "newpass123")
    assert not result.success
    assert "data directory" in result.message


def test_change_password_stops_and_restarts_service_around_successful_reset(
    monkeypatch, tmp_path
):
    fake_service = _FakeServiceManager(initial_state="RUNNING")
    adapter = MariaDBAdapter(service_manager=fake_service)
    monkeypatch.setattr(adapter, "_resolve_datadir", lambda mariadbd: tmp_path)
    monkeypatch.setattr(adapter, "_apply_new_password", lambda mariadbd, datadir, pw: True)

    result = adapter.change_password(RUNNING_INSTALLATION, "newpass123")

    assert fake_service.stop_calls == ["MariaDB"]
    assert fake_service.start_calls == ["MariaDB"]
    assert result.success
    assert result.restored_configuration is True


def test_change_password_restores_service_even_when_reset_fails(monkeypatch, tmp_path):
    fake_service = _FakeServiceManager(initial_state="RUNNING")
    adapter = MariaDBAdapter(service_manager=fake_service)
    monkeypatch.setattr(adapter, "_resolve_datadir", lambda mariadbd: tmp_path)
    monkeypatch.setattr(adapter, "_apply_new_password", lambda mariadbd, datadir, pw: False)

    result = adapter.change_password(RUNNING_INSTALLATION, "newpass123")

    assert not result.success
    assert fake_service.stop_calls == ["MariaDB"]
    assert fake_service.start_calls == ["MariaDB"]


def test_verify_returns_true_on_successful_connection(monkeypatch, tmp_path):
    client = tmp_path / "mariadb"
    client.touch()
    adapter = MariaDBAdapter()
    monkeypatch.setattr(adapter, "_locate_sibling", lambda installation, name: client)

    class _Ok:
        ok = True

    monkeypatch.setattr("app.databases.mariadb.process.run", lambda *a, **k: _Ok())
    assert adapter.verify(RUNNING_INSTALLATION, "newpass123") is True


def test_verify_returns_false_when_client_missing(monkeypatch):
    adapter = MariaDBAdapter()
    monkeypatch.setattr(adapter, "_locate_sibling", lambda installation, name: None)
    assert adapter.verify(RUNNING_INSTALLATION, "newpass123") is False
