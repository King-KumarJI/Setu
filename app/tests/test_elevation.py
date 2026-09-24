"""
Tests for app.utils.elevation.

ctypes.windll only exists on Windows, so every Windows-path test here
monkeypatches app.utils.elevation.is_windows() to True and injects a
fake windll.shell32.IsUserAnAdmin -- this lets the elevated/not
elevated/failed-check branches all be exercised on any platform,
including this Linux sandbox.
"""
from __future__ import annotations

import types

from app.utils import elevation


class _FakeShell32:
    def __init__(self, return_value=None, raises=None):
        self._return_value = return_value
        self._raises = raises

    def IsUserAnAdmin(self):
        if self._raises is not None:
            raise self._raises
        return self._return_value


def _fake_windll(shell32):
    return types.SimpleNamespace(shell32=shell32)


def test_is_windows_reflects_platform(monkeypatch):
    monkeypatch.setattr(elevation.sys, "platform", "win32")
    assert elevation.is_windows() is True

    monkeypatch.setattr(elevation.sys, "platform", "linux")
    assert elevation.is_windows() is False


def test_is_elevated_returns_none_on_non_windows(monkeypatch):
    monkeypatch.setattr(elevation, "is_windows", lambda: False)
    assert elevation.is_elevated() is None


def test_is_elevated_true_when_admin(monkeypatch):
    monkeypatch.setattr(elevation, "is_windows", lambda: True)
    monkeypatch.setattr(
        elevation.ctypes, "windll", _fake_windll(_FakeShell32(return_value=1)), raising=False
    )
    assert elevation.is_elevated() is True


def test_is_elevated_false_when_not_admin(monkeypatch):
    monkeypatch.setattr(elevation, "is_windows", lambda: True)
    monkeypatch.setattr(
        elevation.ctypes, "windll", _fake_windll(_FakeShell32(return_value=0)), raising=False
    )
    assert elevation.is_elevated() is False


def test_is_elevated_returns_none_when_check_fails(monkeypatch):
    monkeypatch.setattr(elevation, "is_windows", lambda: True)
    monkeypatch.setattr(
        elevation.ctypes,
        "windll",
        _fake_windll(_FakeShell32(raises=OSError("boom"))),
        raising=False,
    )
    assert elevation.is_elevated() is None


def test_elevation_warning_none_when_elevated(monkeypatch):
    monkeypatch.setattr(elevation, "is_elevated", lambda: True)
    assert elevation.elevation_warning() is None


def test_elevation_warning_none_when_unknown(monkeypatch):
    monkeypatch.setattr(elevation, "is_elevated", lambda: None)
    assert elevation.elevation_warning() is None


def test_elevation_warning_present_when_not_elevated(monkeypatch):
    monkeypatch.setattr(elevation, "is_elevated", lambda: False)
    message = elevation.elevation_warning()
    assert message is not None
    assert "Administrator" in message
