from app.core.service_manager import NotWindowsError, ServiceManager


def test_stop_service_raises_on_non_windows(monkeypatch):
    manager = ServiceManager()
    monkeypatch.setattr("app.core.service_manager.platform.system", lambda: "Linux")
    try:
        manager.stop_service("MySQL80")
        assert False, "expected NotWindowsError"
    except NotWindowsError:
        pass


def test_start_service_raises_on_non_windows(monkeypatch):
    manager = ServiceManager()
    monkeypatch.setattr("app.core.service_manager.platform.system", lambda: "Linux")
    try:
        manager.start_service("MySQL80")
        assert False, "expected NotWindowsError"
    except NotWindowsError:
        pass


def test_stop_service_returns_true_once_state_reaches_stopped(monkeypatch):
    manager = ServiceManager()
    monkeypatch.setattr(manager, "is_supported", lambda: True)
    monkeypatch.setattr("app.core.service_manager.process.run", lambda *a, **k: _FakeResult())
    monkeypatch.setattr("app.core.service_manager.time.sleep", lambda *_: None)

    states = iter(["RUNNING", "STOPPED"])
    monkeypatch.setattr(manager, "get_service_state", lambda name: next(states))

    assert manager.stop_service("MySQL80", timeout=5) is True


def test_stop_service_returns_false_if_never_reaches_target(monkeypatch):
    manager = ServiceManager()
    monkeypatch.setattr(manager, "is_supported", lambda: True)
    monkeypatch.setattr("app.core.service_manager.process.run", lambda *a, **k: _FakeResult())
    monkeypatch.setattr("app.core.service_manager.time.sleep", lambda *_: None)
    monkeypatch.setattr("app.core.service_manager.time.monotonic", _make_fake_clock())

    monkeypatch.setattr(manager, "get_service_state", lambda name: "RUNNING")

    assert manager.stop_service("MySQL80", timeout=1) is False


class _FakeResult:
    ok = True
    returncode = 0
    stdout = ""
    stderr = ""


def _make_fake_clock():
    ticks = {"n": 0}

    def clock():
        ticks["n"] += 1
        return ticks["n"] * 10  # advances fast past any timeout

    return clock
