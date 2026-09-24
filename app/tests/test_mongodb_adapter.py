from app.core.models import DBMS, DetectionStatus, Installation
from app.databases.mongodb import MongoDBAdapter, _js_string


class _FakeServiceManager:
    def __init__(self, initial_state="RUNNING", binary_path=None):
        self.state = initial_state
        self.binary_path = binary_path
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

    def get_service_binary_path(self, name):
        return self.binary_path


def _installation(tmp_path, service_name="MongoDB"):
    server_exe = tmp_path / "mongod"
    server_exe.touch()
    (tmp_path / "mongosh").touch()
    return Installation(
        dbms=DBMS.MONGODB,
        status=DetectionStatus.SERVER_RUNNING,
        version="7.0.5",
        executable_path=str(server_exe),
        service_name=service_name,
    )


def _write_config(tmp_path, dbpath, auth_enabled=True, port=27017):
    config_path = tmp_path / "mongod.cfg"
    auth_line = "  authorization: enabled\n" if auth_enabled else ""
    config_path.write_text(
        "storage:\n"
        f"  dbPath: {dbpath}\n"
        "net:\n"
        f"  port: {port}\n"
        "security:\n" + auth_line
    )
    return config_path


def test_js_string_escapes_quotes_and_backslashes():
    assert _js_string("it's a \\secret") == "'it\\'s a \\\\secret'"


def test_resolve_config_reads_file_referenced_by_service_binary_path(tmp_path):
    dbpath = tmp_path / "data"
    dbpath.mkdir()
    config_path = _write_config(tmp_path, dbpath)
    binary_path = f'"C:\\MongoDB\\bin\\mongod.exe" --config "{config_path}" --service'
    adapter = MongoDBAdapter(service_manager=_FakeServiceManager(binary_path=binary_path))

    config_text = adapter._resolve_config(_installation(tmp_path))
    assert config_text is not None
    assert "dbPath" in config_text


def test_resolve_dbpath_parses_config(tmp_path):
    dbpath = tmp_path / "data"
    dbpath.mkdir()
    config_path = _write_config(tmp_path, dbpath)
    binary_path = f'--config "{config_path}"'
    adapter = MongoDBAdapter(service_manager=_FakeServiceManager(binary_path=binary_path))

    assert adapter._resolve_dbpath(_installation(tmp_path)) == dbpath


def test_resolve_dbpath_returns_none_when_path_does_not_exist(tmp_path):
    config_path = _write_config(tmp_path, tmp_path / "does-not-exist")
    binary_path = f'--config "{config_path}"'
    adapter = MongoDBAdapter(service_manager=_FakeServiceManager(binary_path=binary_path))

    assert adapter._resolve_dbpath(_installation(tmp_path)) is None


def test_resolve_port_parses_config(tmp_path):
    dbpath = tmp_path / "data"
    dbpath.mkdir()
    config_path = _write_config(tmp_path, dbpath, port=27018)
    binary_path = f'--config "{config_path}"'
    adapter = MongoDBAdapter(service_manager=_FakeServiceManager(binary_path=binary_path))

    assert adapter._resolve_port(_installation(tmp_path)) == 27018


def test_config_requires_auth_detects_enabled(tmp_path):
    dbpath = tmp_path / "data"
    dbpath.mkdir()
    config_path = _write_config(tmp_path, dbpath, auth_enabled=True)
    binary_path = f'--config "{config_path}"'
    adapter = MongoDBAdapter(service_manager=_FakeServiceManager(binary_path=binary_path))

    assert adapter._config_requires_auth(_installation(tmp_path)) is True


def test_config_requires_auth_false_when_absent(tmp_path):
    dbpath = tmp_path / "data"
    dbpath.mkdir()
    config_path = _write_config(tmp_path, dbpath, auth_enabled=False)
    binary_path = f'--config "{config_path}"'
    adapter = MongoDBAdapter(service_manager=_FakeServiceManager(binary_path=binary_path))

    assert adapter._config_requires_auth(_installation(tmp_path)) is False


def test_change_password_refuses_client_only_installation():
    adapter = MongoDBAdapter()
    installation = Installation(dbms=DBMS.MONGODB, status=DetectionStatus.EXECUTABLE_FOUND)
    result = adapter.change_password(installation, "newpass123")
    assert not result.success
    assert "client was detected" in result.message


def test_change_password_refuses_when_dbpath_unresolved(tmp_path, monkeypatch):
    adapter = MongoDBAdapter(service_manager=_FakeServiceManager(binary_path=None))
    result = adapter.change_password(_installation(tmp_path), "newpass123")
    assert not result.success
    assert "data directory" in result.message


def test_change_password_refuses_when_mongosh_missing(tmp_path, monkeypatch):
    dbpath = tmp_path / "data"
    dbpath.mkdir()
    config_path = _write_config(tmp_path, dbpath)
    binary_path = f'--config "{config_path}"'
    adapter = MongoDBAdapter(service_manager=_FakeServiceManager(binary_path=binary_path))
    installation = _installation(tmp_path)
    (tmp_path / "mongosh").unlink()  # remove the sibling created by _installation

    result = adapter.change_password(installation, "newpass123")
    assert not result.success
    assert "mongosh" in result.message


def test_change_password_stops_and_restarts_service_around_successful_reset(tmp_path):
    dbpath = tmp_path / "data"
    dbpath.mkdir()
    config_path = _write_config(tmp_path, dbpath)
    binary_path = f'--config "{config_path}"'
    fake_service = _FakeServiceManager(initial_state="RUNNING", binary_path=binary_path)
    adapter = MongoDBAdapter(service_manager=fake_service)
    adapter._apply_new_password = lambda mongod, mongosh, dbpath_, pw: True

    result = adapter.change_password(_installation(tmp_path), "newpass123")

    assert fake_service.stop_calls == ["MongoDB"]
    assert fake_service.start_calls == ["MongoDB"]
    assert result.success
    assert result.restored_configuration is True


def test_change_password_restores_service_even_when_reset_fails(tmp_path):
    dbpath = tmp_path / "data"
    dbpath.mkdir()
    config_path = _write_config(tmp_path, dbpath)
    binary_path = f'--config "{config_path}"'
    fake_service = _FakeServiceManager(initial_state="RUNNING", binary_path=binary_path)
    adapter = MongoDBAdapter(service_manager=fake_service)
    adapter._apply_new_password = lambda mongod, mongosh, dbpath_, pw: False

    result = adapter.change_password(_installation(tmp_path), "newpass123")

    assert not result.success
    assert "root" in result.message  # names the assumed admin-username limitation
    assert fake_service.stop_calls == ["MongoDB"]
    assert fake_service.start_calls == ["MongoDB"]


def test_verify_returns_true_on_successful_auth(monkeypatch, tmp_path):
    mongosh = tmp_path / "mongosh"
    mongosh.touch()
    adapter = MongoDBAdapter()
    monkeypatch.setattr(adapter, "_locate_sibling", lambda installation, name: mongosh)
    monkeypatch.setattr(adapter, "_resolve_port", lambda installation: 27017)

    class _Ok:
        ok = True

    monkeypatch.setattr("app.databases.mongodb.process.run", lambda *a, **k: _Ok())
    assert adapter.verify(_installation(tmp_path), "newpass123") is True


def test_verify_returns_false_when_mongosh_missing(monkeypatch, tmp_path):
    adapter = MongoDBAdapter()
    monkeypatch.setattr(adapter, "_locate_sibling", lambda installation, name: None)
    assert adapter.verify(_installation(tmp_path), "newpass123") is False


def test_verify_cleans_up_script_file(monkeypatch, tmp_path):
    mongosh = tmp_path / "mongosh"
    mongosh.touch()
    adapter = MongoDBAdapter()
    monkeypatch.setattr(adapter, "_locate_sibling", lambda installation, name: mongosh)
    monkeypatch.setattr(adapter, "_resolve_port", lambda installation: 27017)

    written = {}
    original_write = MongoDBAdapter._write_script

    def _tracking_write(content):
        path = original_write(content)
        written["path"] = path
        return path

    monkeypatch.setattr(MongoDBAdapter, "_write_script", staticmethod(_tracking_write))

    class _Ok:
        ok = True

    monkeypatch.setattr("app.databases.mongodb.process.run", lambda *a, **k: _Ok())
    adapter.verify(_installation(tmp_path), "newpass123")

    assert not written["path"].exists()
