import os
import stat
import sys

from app.core.models import DBMS, DetectionStatus, Installation
from app.databases.mysql import MySQLAdapter


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
    """The temp-file helpers restrict their output to the owner via
    os.chmod(path, S_IRUSR | S_IWUSR). On POSIX this produces exactly
    0o600. On Windows, os.chmod can only toggle the read-only
    attribute -- it cannot express "owner only" the way POSIX
    permission bits do, so a writable file always reports as rw for
    everyone there. The meaningful, checkable invariant on Windows is
    just "still writable" (i.e. the call didn't accidentally leave the
    file read-only); real access restriction there comes from the file
    living in the user's own %TEMP%, which NTFS already restricts by
    default (see 07-hardening-review.md Section 4.2)."""
    if sys.platform == "win32":
        assert os.access(path, os.W_OK)
    else:
        assert stat.S_IMODE(path.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR


class _FakeServiceManager:
    def __init__(self, initial_state="RUNNING", binary_path=None):
        self.state = initial_state
        self.stop_calls = []
        self.start_calls = []
        self.stop_should_succeed = True
        self.start_should_succeed = True
        self.binary_path = binary_path

    def get_service_state(self, name):
        return self.state

    def get_service_binary_path(self, name):
        return self.binary_path

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
    dbms=DBMS.MYSQL,
    status=DetectionStatus.SERVER_RUNNING,
    version="8.0.35",
    executable_path="/opt/mysql/bin/mysqld",
    service_name="MySQL80",
)


# ----------------------------------------------------------------------
# Discovery helpers
# ----------------------------------------------------------------------
def test_resolve_datadir_parses_verbose_help_output(tmp_path):
    fake_datadir = tmp_path / "data"
    fake_datadir.mkdir()
    mysqld = _make_executable(
        tmp_path / "mysqld",
        "mysqld  Ver 8.0.35\n"
        "\n"
        "Variables (--variable-name=value)\n"
        "---------------------------------- -----------------------------\n"
        f"datadir                            {fake_datadir}",
    )
    adapter = MySQLAdapter()
    assert adapter._resolve_datadir(mysqld) == fake_datadir


def test_resolve_datadir_returns_none_when_path_does_not_exist(tmp_path):
    mysqld = _make_executable(tmp_path / "mysqld", "datadir   /no/such/directory")
    adapter = MySQLAdapter()
    assert adapter._resolve_datadir(mysqld) is None


def test_resolve_datadir_returns_none_when_executable_fails(tmp_path):
    adapter = MySQLAdapter()
    assert adapter._resolve_datadir(tmp_path / "does-not-exist") is None


def test_resolve_datadir_prefers_service_defaults_file_over_compiled_default(tmp_path):
    """Regression test for a real bug found against an actual MySQL 8.0
    Windows install (Rule 9): mysqld invoked bare reports a compiled-in
    default datadir under Program Files that the official Windows
    installer never actually creates -- the real datadir only shows up
    once mysqld is pointed at the same --defaults-file the Windows
    service itself was registered with. Simulates that shape: the
    bare-invocation output claims a datadir that doesn't exist, while
    invoking with --defaults-file reports the real, existing one."""
    real_datadir = tmp_path / "programdata" / "data"
    real_datadir.mkdir(parents=True)
    fake_ini = tmp_path / "programdata" / "my.ini"
    fake_ini.write_text("[mysqld]\n")

    missing_datadir = tmp_path / "program-files" / "data"
    bare_output = "mysqld  Ver 8.0.35\ndatadir   " + str(missing_datadir)
    with_defaults_output = "mysqld  Ver 8.0.35\ndatadir   " + str(real_datadir)

    mysqld = tmp_path / ("mysqld.bat" if sys.platform == "win32" else "mysqld")
    if sys.platform == "win32":
        # A bare invocation (no --defaults-file argument) prints the
        # compiled default; any invocation carrying --defaults-file
        # prints the real, ini-resolved one.
        script = (
            "@echo off\r\n"
            "echo %1 | findstr /C:\"--defaults-file\" >nul\r\n"
            "if %errorlevel%==0 (\r\n"
            "  echo " + with_defaults_output.replace("\n", "\r\necho ") + "\r\n"
            ") else (\r\n"
            "  echo " + bare_output.replace("\n", "\r\necho ") + "\r\n"
            ")\r\n"
        )
        mysqld.write_text(script)
    else:
        script = (
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            "  --defaults-file=*)\n"
            "    printf '%s\\n' \"" + with_defaults_output + "\"\n"
            "    ;;\n"
            "  *)\n"
            "    printf '%s\\n' \"" + bare_output + "\"\n"
            "    ;;\n"
            "esac\n"
        )
        mysqld.write_text(script)
        mysqld.chmod(mysqld.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    fake_service = _FakeServiceManager(
        binary_path='"' + str(mysqld) + '" --defaults-file="' + str(fake_ini) + '" MySQL80'
    )
    adapter = MySQLAdapter(service_manager=fake_service)

    assert adapter._resolve_datadir(mysqld, "MySQL80") == real_datadir
    # And without a service name, falls back to the (here, non-existent) compiled default.
    assert adapter._resolve_datadir(mysqld, None) is None


def test_locate_sibling_finds_matching_extension(tmp_path):
    mysqld = tmp_path / "mysqld"
    mysqld.touch()
    client = tmp_path / "mysql"
    client.touch()
    installation = Installation(
        dbms=DBMS.MYSQL, status=DetectionStatus.SERVER_RUNNING, executable_path=str(mysqld)
    )
    adapter = MySQLAdapter()
    assert adapter._locate_sibling(installation, "mysql") == client


def test_locate_sibling_returns_none_when_absent(tmp_path, monkeypatch):
    mysqld = tmp_path / "mysqld"
    mysqld.touch()
    installation = Installation(
        dbms=DBMS.MYSQL, status=DetectionStatus.SERVER_RUNNING, executable_path=str(mysqld)
    )
    monkeypatch.setattr("app.databases.mysql.which", lambda name: None)
    adapter = MySQLAdapter()
    assert adapter._locate_sibling(installation, "mysql") is None


# ----------------------------------------------------------------------
# Temp-file helpers
# ----------------------------------------------------------------------
def test_write_init_file_contains_escaped_alter_user_statement():
    path = MySQLAdapter._write_init_file("it's a secret")
    try:
        content = path.read_text()
        assert "ALTER USER 'root'@'localhost'" in content
        assert "it''s a secret" in content
        _assert_owner_only_permissions(path)
    finally:
        path.unlink(missing_ok=True)


def test_write_client_defaults_file_contains_password():
    path = MySQLAdapter._write_client_defaults_file('pa"ss')
    try:
        content = path.read_text()
        assert "[client]" in content
        assert 'pa\\"ss' in content
        _assert_owner_only_permissions(path)
    finally:
        path.unlink(missing_ok=True)


def test_delete_temp_file_removes_it(tmp_path):
    target = tmp_path / "gone.txt"
    target.write_text("x")
    MySQLAdapter._delete_temp_file(target)
    assert not target.exists()


# ----------------------------------------------------------------------
# change_password orchestration (mocked service control + reset step --
# no real mysqld is available in this environment; see module docstring)
# ----------------------------------------------------------------------
def test_change_password_refuses_client_only_installation():
    adapter = MySQLAdapter()
    installation = Installation(dbms=DBMS.MYSQL, status=DetectionStatus.EXECUTABLE_FOUND)
    result = adapter.change_password(installation, "newpass123")
    assert not result.success
    assert "client was detected" in result.message


def test_change_password_refuses_when_no_executable_path():
    adapter = MySQLAdapter()
    installation = Installation(dbms=DBMS.MYSQL, status=DetectionStatus.SERVER_RUNNING)
    result = adapter.change_password(installation, "newpass123")
    assert not result.success
    assert "No mysqld executable path" in result.message


def test_change_password_refuses_when_datadir_unresolved(monkeypatch):
    adapter = MySQLAdapter()
    monkeypatch.setattr(adapter, "_resolve_datadir", lambda mysqld, service_name=None: None)
    result = adapter.change_password(RUNNING_INSTALLATION, "newpass123")
    assert not result.success
    assert "data directory" in result.message


def test_change_password_stops_and_restarts_service_around_successful_reset(
    monkeypatch, tmp_path
):
    fake_service = _FakeServiceManager(initial_state="RUNNING")
    adapter = MySQLAdapter(service_manager=fake_service)
    monkeypatch.setattr(adapter, "_resolve_datadir", lambda mysqld, service_name=None: tmp_path)
    monkeypatch.setattr(adapter, "_apply_new_password", lambda mysqld, datadir, pw: True)

    result = adapter.change_password(RUNNING_INSTALLATION, "newpass123")

    assert fake_service.stop_calls == ["MySQL80"]
    assert fake_service.start_calls == ["MySQL80"]
    assert result.success
    assert result.restored_configuration is True


def test_change_password_restores_service_even_when_reset_fails(monkeypatch, tmp_path):
    fake_service = _FakeServiceManager(initial_state="RUNNING")
    adapter = MySQLAdapter(service_manager=fake_service)
    monkeypatch.setattr(adapter, "_resolve_datadir", lambda mysqld, service_name=None: tmp_path)
    monkeypatch.setattr(adapter, "_apply_new_password", lambda mysqld, datadir, pw: False)

    result = adapter.change_password(RUNNING_INSTALLATION, "newpass123")

    assert not result.success
    assert fake_service.stop_calls == ["MySQL80"]
    assert fake_service.start_calls == ["MySQL80"]


def test_change_password_aborts_cleanly_if_service_will_not_stop(monkeypatch, tmp_path):
    fake_service = _FakeServiceManager(initial_state="RUNNING")
    fake_service.stop_should_succeed = False
    adapter = MySQLAdapter(service_manager=fake_service)
    monkeypatch.setattr(adapter, "_resolve_datadir", lambda mysqld, service_name=None: tmp_path)
    called = {"apply": False}

    def _mark_called(*args, **kwargs):
        called["apply"] = True
        return True

    monkeypatch.setattr(adapter, "_apply_new_password", _mark_called)

    result = adapter.change_password(RUNNING_INSTALLATION, "newpass123")

    assert not result.success
    assert called["apply"] is False


def test_change_password_reports_when_restart_fails(monkeypatch, tmp_path):
    fake_service = _FakeServiceManager(initial_state="RUNNING")
    fake_service.start_should_succeed = False
    adapter = MySQLAdapter(service_manager=fake_service)
    monkeypatch.setattr(adapter, "_resolve_datadir", lambda mysqld, service_name=None: tmp_path)
    monkeypatch.setattr(adapter, "_apply_new_password", lambda mysqld, datadir, pw: True)

    result = adapter.change_password(RUNNING_INSTALLATION, "newpass123")

    assert result.success
    assert result.verified is False
    assert result.restored_configuration is False
    assert "could not be restarted" in result.message


# ----------------------------------------------------------------------
# verify()
# ----------------------------------------------------------------------
def test_verify_returns_true_on_successful_connection(monkeypatch, tmp_path):
    client = tmp_path / "mysql"
    client.touch()
    adapter = MySQLAdapter()
    monkeypatch.setattr(adapter, "_locate_sibling", lambda installation, name: client)

    class _Ok:
        ok = True

    monkeypatch.setattr("app.databases.mysql.process.run", lambda *a, **k: _Ok())
    assert adapter.verify(RUNNING_INSTALLATION, "newpass123") is True


def test_verify_returns_false_when_client_missing(monkeypatch):
    adapter = MySQLAdapter()
    monkeypatch.setattr(adapter, "_locate_sibling", lambda installation, name: None)
    assert adapter.verify(RUNNING_INSTALLATION, "newpass123") is False


def test_verify_returns_false_on_connection_failure(monkeypatch, tmp_path):
    client = tmp_path / "mysql"
    client.touch()
    adapter = MySQLAdapter()
    monkeypatch.setattr(adapter, "_locate_sibling", lambda installation, name: client)

    class _Fail:
        ok = False

    monkeypatch.setattr("app.databases.mysql.process.run", lambda *a, **k: _Fail())
    assert adapter.verify(RUNNING_INSTALLATION, "newpass123") is False


def test_verify_cleans_up_defaults_file_even_on_exception(monkeypatch, tmp_path):
    client = tmp_path / "mysql"
    client.touch()
    adapter = MySQLAdapter()
    monkeypatch.setattr(adapter, "_locate_sibling", lambda installation, name: client)

    written = {}

    def _fake_write(password):
        p = tmp_path / "defaults.cnf"
        p.write_text("[client]\n")
        written["path"] = p
        return p

    monkeypatch.setattr(MySQLAdapter, "_write_client_defaults_file", staticmethod(_fake_write))

    def _boom(*a, **k):
        raise RuntimeError("network unreachable")

    monkeypatch.setattr("app.databases.mysql.process.run", _boom)

    assert adapter.verify(RUNNING_INSTALLATION, "newpass123") is False
    assert not written["path"].exists()
