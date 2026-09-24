# Changelog

All notable changes to Setu are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Packaging: `packaging/build.ps1` and `packaging/setu.spec` produce a
  single portable `Setu.exe` via PyInstaller.
- Public release scaffolding: LICENSE (MIT), SECURITY.md, CI workflow.

## [0.1.0] - 2026-09-24

### Added
- Detection engine for MySQL, PostgreSQL, MariaDB, MongoDB, and Redis
  local installations.
- PySide6 GUI with elevation-awareness banner (warns when not run as
  Administrator, since most password-change operations need to
  stop/start a Windows service).
- Password-reset adapters for MySQL, PostgreSQL, MariaDB, MongoDB, and
  Redis, each using the engine's own tooling (e.g. `--init-file`,
  `.pgpass`) rather than embedding credentials in process arguments.
- Secret-safe logging and temp-file handling: credentials are never
  logged, and temp files used to pass a new password to a database
  CLI are deleted immediately after use.
- 137 unit/mock-level tests.

### Known limitations
- Windows-only; Phase 8 (Linux/macOS support) is deferred until
  Windows support is established as stable through real-world use.
- No adapter has yet been exercised against a real running database
  server end-to-end (mocked/unit-level testing only) — see
  `08-release-checklist.md`.
