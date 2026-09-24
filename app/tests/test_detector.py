import os
import stat
import sys

import pytest

from app.core.detector import DetectionEngine
from app.core.models import DBMS, DetectionStatus
from app.core.service_manager import ServiceInfo


def _make_executable(path, output):
    """Create a fake "executable" that prints `output` to stdout when
    run -- portable across this Linux development sandbox and the real
    Windows target. Windows has no shebang interpretation and no POSIX
    exec bit, so a plain shell script here would fail to launch at all
    (WinError 193 "not a valid Win32 application"); the equivalent on
    Windows is a .bat file, which also gives the file the .bat
    extension shutil.which() requires on Windows (it only matches names
    ending in a PATHEXT extension there, never a bare name)."""
    if sys.platform == "win32":
        exe_path = path.with_name(path.name + ".bat")
        exe_path.write_text(f"@echo off\r\necho {output}\r\n")
        return exe_path
    path.write_text(f"#!/bin/sh\necho '{output}'\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture
def fake_path_dir(tmp_path, monkeypatch):
    """A PATH directory containing a fake 'mysql' client, so PATH-based
    discovery can be exercised without a real DBMS installed. Returns
    the created executable's own path (name may carry a platform
    suffix, e.g. "mysql.bat" on Windows -- see _make_executable)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe_path = _make_executable(bin_dir / "mysql", "mysql  Ver 8.0.35 for Linux")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return exe_path


def test_find_executables_locates_fake_binary_on_path(fake_path_dir):
    engine = DetectionEngine()
    found = engine.find_executables(("mysql",))
    assert len(found) == 1
    # .stem rather than .name: on Windows the fake executable is
    # "mysql.bat" (see _make_executable), on POSIX it's bare "mysql".
    assert found[0].stem == "mysql"


def test_find_executables_returns_empty_when_not_on_path(monkeypatch):
    monkeypatch.setenv("PATH", "")
    engine = DetectionEngine()
    assert engine.find_executables(("definitely-not-a-real-binary",)) == []


def test_get_version_parses_output(fake_path_dir):
    engine = DetectionEngine()
    # fake_path_dir is already the executable's own path (see the
    # fixture) -- not a directory to join "mysql" onto.
    version = engine.get_version(fake_path_dir, ("--version",))
    assert version == "8.0.35"


def test_get_version_returns_none_for_missing_executable(tmp_path):
    engine = DetectionEngine()
    version = engine.get_version(tmp_path / "does-not-exist", ("--version",))
    assert version is None


def test_detect_reports_not_detected_when_nothing_found(monkeypatch):
    engine = DetectionEngine()
    monkeypatch.setattr(engine, "find_executables", lambda names: [])
    monkeypatch.setattr(engine, "find_in_program_files", lambda names, hint: [])
    monkeypatch.setattr(engine.service_manager, "find_services", lambda patterns: [])

    result = engine.detect(DBMS.REDIS)
    assert result.status == DetectionStatus.NOT_DETECTED
    assert result.installations == []


def test_detect_reports_executable_found_without_implying_server(monkeypatch, fake_path_dir):
    engine = DetectionEngine()
    monkeypatch.setattr(engine, "find_in_program_files", lambda names, hint: [])
    monkeypatch.setattr(engine.service_manager, "find_services", lambda patterns: [])

    result = engine.detect(DBMS.MYSQL)
    assert result.status == DetectionStatus.EXECUTABLE_FOUND
    assert result.installations[0].service_name is None


def test_detect_reports_server_found_when_service_stopped(monkeypatch, tmp_path):
    engine = DetectionEngine()
    server_exe = _make_executable(tmp_path / "mysqld", "mysqld  Ver 8.0.35")

    monkeypatch.setattr(
        engine, "find_executables", lambda names: [server_exe] if "mysqld" in names else []
    )
    monkeypatch.setattr(engine, "find_in_program_files", lambda names, hint: [])
    monkeypatch.setattr(
        engine.service_manager,
        "find_services",
        lambda patterns: [ServiceInfo(name="MySQL80", display_name="MySQL80", state="STOPPED")],
    )

    result = engine.detect(DBMS.MYSQL)
    assert result.status == DetectionStatus.SERVER_FOUND
    assert result.installations[0].service_name == "MySQL80"


def test_detect_escalates_to_server_running_when_service_running(monkeypatch, tmp_path):
    engine = DetectionEngine()
    server_exe = _make_executable(tmp_path / "mysqld", "mysqld  Ver 8.0.35")

    monkeypatch.setattr(
        engine, "find_executables", lambda names: [server_exe] if "mysqld" in names else []
    )
    monkeypatch.setattr(engine, "find_in_program_files", lambda names, hint: [])
    monkeypatch.setattr(
        engine.service_manager,
        "find_services",
        lambda patterns: [ServiceInfo(name="MySQL80", display_name="MySQL80", state="RUNNING")],
    )

    result = engine.detect(DBMS.MYSQL)
    assert result.status == DetectionStatus.SERVER_RUNNING
    assert result.installations[0].service_name == "MySQL80"


def test_detect_reports_multiple_installations(monkeypatch, tmp_path):
    engine = DetectionEngine()
    exe_a = _make_executable(tmp_path / "mysqld_a", "mysqld  Ver 8.0.35")
    exe_b = _make_executable(tmp_path / "mysqld_b", "mysqld  Ver 5.7.44")

    monkeypatch.setattr(engine, "find_executables", lambda names: [exe_a, exe_b])
    monkeypatch.setattr(engine, "find_in_program_files", lambda names, hint: [])
    monkeypatch.setattr(engine.service_manager, "find_services", lambda patterns: [])

    result = engine.detect(DBMS.MYSQL)
    assert result.has_multiple_installations
    assert len(result.installations) == 2


def test_detect_all_covers_every_dbms(monkeypatch):
    engine = DetectionEngine()
    monkeypatch.setattr(engine, "find_executables", lambda names: [])
    monkeypatch.setattr(engine, "find_in_program_files", lambda names, hint: [])
    monkeypatch.setattr(engine.service_manager, "find_services", lambda patterns: [])

    results = engine.detect_all()
    assert set(results.keys()) == set(DBMS)
    assert all(r.status == DetectionStatus.NOT_DETECTED for r in results.values())
