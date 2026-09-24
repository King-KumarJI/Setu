# Setu — DB Password Reset Tool

[![Build](https://github.com/OWNER/setu/actions/workflows/build.yml/badge.svg)](https://github.com/OWNER/setu/actions/workflows/build.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Windows-first desktop utility that detects locally installed database
systems (MySQL, PostgreSQL, MariaDB, MongoDB, Redis) and provides a
simple GUI for an administrator to reset a forgotten local database
password.

See `01-architecture.md` through `06-rules.md` for the full design,
PRD, phased roadmap, and engineering rules this codebase follows.
`07-hardening-review.md` records the Phase 6 security/error-handling/
secret-handling review. `04-phases.md` is the source of truth for what
is implemented: Phases 0 through 6 (Foundation, Detection, GUI MVP,
MySQL, PostgreSQL, MariaDB/MongoDB/Redis, Hardening) are complete.
Phase 7 (Packaging) adds the pieces in this README's "Build a portable
executable" section below. Phase 8 (Linux/macOS) is explicitly
deferred.

**Prerequisites:** Windows 10/11, Python 3.11+, Administrator rights
for anything beyond detection (most password-change operations stop
and start a Windows service or touch a Program Files-owned
configuration file).

## Download

Grab the latest portable `Setu.exe` from the
[Releases page](https://github.com/OWNER/setu/releases/latest) — no
installer, just download and run. Each release also publishes a
`Setu.exe.sha256` checksum file so you can verify the download before
running an admin-elevated tool:

```powershell
Get-FileHash Setu.exe -Algorithm SHA256
# compare against the value in Setu.exe.sha256
```

If you'd rather run from source or build it yourself, see "Setup" and
"Build a portable executable" below.

## Trust & security

Setu does not make network calls, phone home, or collect telemetry —
everything it does is local to your machine. It's fully open source
under the MIT license, so the code doing anything with your database
credentials is readable by anyone, not just trusted on faith. See
[SECURITY.md](SECURITY.md) to report a vulnerability, and
`07-hardening-review.md` in this repo for the internal security review
its secret-handling and temp-file logic was built against.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
```

## Run

```powershell
python -m app.main
```

Run the terminal (or the built `Setu.exe`) as Administrator — the app
will still open and detect installed databases either way, but will
warn you up front if it isn't elevated, since changing a password
almost always needs to stop/start a Windows service.

## Test

```powershell
pytest
```

137 tests as of Phase 6, all mocked/unit-level — see
`07-hardening-review.md` Section 1 and Section 9 for the standing
limitation that no adapter has been run against a real database server
yet.

## Build a portable executable

```powershell
cd C:\path\to\setu
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

This must be run directly on Windows (not in a Linux/WSL shell) with
network access to PyPI — it creates its own `.venv`, installs
`requirements-dev.txt` plus PyInstaller, runs the test suite as a
build gate, and produces a single portable `dist\Setu.exe`. No
installer, no registry writes — copy the `.exe` wherever you like. See
`packaging/setu.spec` for the build configuration and
`08-release-checklist.md` before shipping a build to anyone else.

## Layout

```text
app/
├── main.py               entry point
├── gui/                  PySide6 UI (main_window.py is Qt wiring;
│                         presentation.py is the Qt-free status/error
│                         text logic, independently testable)
├── core/                 detection engine, orchestration, models,
│                         service control, password-change orchestration
├── databases/             one adapter per DBMS (base.py is the interface;
│                         mock.py is used by GUI/orchestration tests)
├── utils/                 logging + secret redaction, safe subprocess
│                         execution, path discovery, elevation detection
└── tests/

packaging/
├── setu.spec              PyInstaller build spec
├── version_info.txt       Windows version-resource metadata
└── build.ps1               the build script described above

app/resources/
└── icon.ico                application icon
```

## License

MIT — see [LICENSE](LICENSE).
