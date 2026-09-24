from app.core.models import DBMS, DetectionStatus, Installation
from app.databases.redis import RedisAdapter


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


def _installation(tmp_path, service_name="Redis"):
    server_exe = tmp_path / "redis-server"
    server_exe.touch()
    (tmp_path / "redis-cli").touch()
    return Installation(
        dbms=DBMS.REDIS,
        status=DetectionStatus.SERVER_RUNNING,
        version="7.2.4",
        executable_path=str(server_exe),
        service_name=service_name,
    )


# ----------------------------------------------------------------------
# Discovery / config editing
# ----------------------------------------------------------------------
def test_resolve_conf_path_from_service_binary_path(tmp_path):
    conf_path = tmp_path / "redis.conf"
    conf_path.write_text("port 6379\n")
    binary_path = f'"C:\\Redis\\redis-server.exe" "{conf_path}" --service-run'
    adapter = RedisAdapter(service_manager=_FakeServiceManager(binary_path=binary_path))
    assert adapter._resolve_conf_path(_installation(tmp_path)) == conf_path


def test_resolve_conf_path_returns_none_without_service(tmp_path):
    adapter = RedisAdapter(service_manager=_FakeServiceManager(binary_path=None))
    assert adapter._resolve_conf_path(_installation(tmp_path, service_name=None)) is None


def test_set_requirepass_replaces_active_directive():
    content = "port 6379\nrequirepass oldpass\nmaxmemory 100mb\n"
    result = RedisAdapter._set_requirepass(content, "newpass")
    assert 'requirepass "newpass"' in result
    assert "oldpass" not in result
    assert "maxmemory 100mb" in result


def test_set_requirepass_ignores_commented_example_line():
    content = "# requirepass foobared\nport 6379\n"
    result = RedisAdapter._set_requirepass(content, "newpass")
    assert "# requirepass foobared" in result  # left alone, not uncommented
    assert 'requirepass "newpass"' in result


def test_set_requirepass_appends_when_absent():
    content = "port 6379\n"
    result = RedisAdapter._set_requirepass(content, "newpass")
    assert result == 'port 6379\nrequirepass "newpass"\n'


def test_set_requirepass_escapes_quotes_and_backslashes():
    result = RedisAdapter._set_requirepass("", 'pa"ss\\word')
    assert 'requirepass "pa\\"ss\\\\word"' in result


def test_write_conf_and_confirm_round_trips(tmp_path):
    path = tmp_path / "redis.conf"
    path.write_text("old\n")
    assert RedisAdapter._write_conf_and_confirm(path, "new\n") is True
    assert path.read_text() == "new\n"


# ----------------------------------------------------------------------
# change_password orchestration
# ----------------------------------------------------------------------
def test_change_password_refuses_client_only_installation():
    adapter = RedisAdapter()
    installation = Installation(dbms=DBMS.REDIS, status=DetectionStatus.EXECUTABLE_FOUND)
    result = adapter.change_password(installation, "newpass123")
    assert not result.success
    assert "client was detected" in result.message


def test_change_password_refuses_when_conf_unresolved(tmp_path):
    adapter = RedisAdapter(service_manager=_FakeServiceManager(binary_path=None))
    result = adapter.change_password(_installation(tmp_path), "newpass123")
    assert not result.success
    assert "redis.conf location" in result.message


def test_change_password_stops_writes_and_restarts_on_success(tmp_path):
    conf_path = tmp_path / "redis.conf"
    conf_path.write_text("port 6379\n")
    binary_path = f'"{conf_path}"'
    fake_service = _FakeServiceManager(initial_state="RUNNING", binary_path=binary_path)
    adapter = RedisAdapter(service_manager=fake_service)

    result = adapter.change_password(_installation(tmp_path), "newpass123")

    assert fake_service.stop_calls == ["Redis"]
    assert fake_service.start_calls == ["Redis"]
    assert result.success
    assert result.restored_configuration is None  # nothing needed restoring -- new state is intended
    assert 'requirepass "newpass123"' in conf_path.read_text()


def test_change_password_rolls_back_when_service_wont_start_with_new_config(tmp_path):
    original_content = "port 6379\n"
    conf_path = tmp_path / "redis.conf"
    conf_path.write_text(original_content)
    binary_path = f'"{conf_path}"'
    fake_service = _FakeServiceManager(initial_state="RUNNING", binary_path=binary_path)
    fake_service.start_should_succeed = False
    adapter = RedisAdapter(service_manager=fake_service)

    result = adapter.change_password(_installation(tmp_path), "newpass123")

    assert not result.success
    assert result.restored_configuration is True
    assert conf_path.read_text() == original_content  # rolled back, not left with the new password


def test_verify_returns_true_when_ping_succeeds(monkeypatch, tmp_path):
    redis_cli = tmp_path / "redis-cli"
    redis_cli.touch()
    adapter = RedisAdapter()
    monkeypatch.setattr(adapter, "_locate_sibling", lambda installation, name: redis_cli)

    class _Ok:
        ok = True
        stdout = "PONG\n"

    monkeypatch.setattr("app.databases.redis.process.run", lambda *a, **k: _Ok())
    assert adapter.verify(_installation(tmp_path), "newpass123") is True


def test_verify_returns_false_when_reply_is_not_pong(monkeypatch, tmp_path):
    redis_cli = tmp_path / "redis-cli"
    redis_cli.touch()
    adapter = RedisAdapter()
    monkeypatch.setattr(adapter, "_locate_sibling", lambda installation, name: redis_cli)

    class _WrongPassword:
        ok = True  # redis-cli's exit code is not reliable for auth errors
        stdout = "(error) WRONGPASS invalid username-password pair\n"

    monkeypatch.setattr("app.databases.redis.process.run", lambda *a, **k: _WrongPassword())
    assert adapter.verify(_installation(tmp_path), "newpass123") is False


def test_verify_returns_false_when_client_missing(monkeypatch, tmp_path):
    adapter = RedisAdapter()
    monkeypatch.setattr(adapter, "_locate_sibling", lambda installation, name: None)
    assert adapter.verify(_installation(tmp_path), "newpass123") is False
