# DB Password Reset Tool — Project Memory

This document is the persistent project context for future development sessions.

## Project Identity

Name: DB Password Reset Tool

Type: Windows-first desktop developer utility

Primary stack: Python 3.11+ / PySide6

Primary purpose:

> Detect locally installed database software and provide a simple interface for changing an administrator-controlled database password.

## Core User Experience

The user should only need to:

1. Select a DBMS.
2. Enter a new password.
3. Confirm the password.
4. Click Change Password.

The application handles discovery and database-specific complexity internally.

## Initial DBMS Targets

- MySQL
- PostgreSQL
- MongoDB
- MariaDB
- Redis

Initial full implementations should prioritize MySQL and PostgreSQL.

Other DBMS can begin with detection and adapter scaffolding.

## Discovery Philosophy

PATH/environment discovery is an important first signal.

Examples:

- `mysql.exe`
- `mysqld.exe`
- `psql.exe`
- `postgres.exe`
- `mongosh.exe`
- `mongod.exe`
- `mariadb.exe`
- `mariadbd.exe`
- `redis-cli.exe`
- `redis-server.exe`

But PATH alone is insufficient.

The system must distinguish client executable availability from actual server availability and running state.

## Architectural Principles

- Adapter-based DBMS support.
- Separation of GUI and backend.
- No hardcoded user-specific paths.
- No giant database-specific conditional.
- Detection and password operations are separate concerns.
- Every sensitive operation is explicit.
- Passwords are never persisted or logged.

## Current MVP Direction

Platform: Windows

GUI: PySide6

Detection:
- PATH
- executable discovery
- Windows Services
- version detection

Database implementations:
- MySQL
- PostgreSQL

Scaffolding:
- MongoDB
- MariaDB
- Redis

## Important Security Constraint

The project is for systems the user legitimately administers.

It must not become a credential-extraction or unauthorized-access tool.

Do not add functionality that:

- dumps existing credentials
- extracts passwords
- steals authentication material
- bypasses authentication on remote systems
- transmits secrets
- stores passwords

## Future Ideas

Potential future features:

- Linux support
- macOS support
- database health diagnostics
- service start/stop/restart
- port detection
- configuration diagnostics
- packaged executable
- plugin-style adapter discovery
- dry-run/diagnostic mode

These are future ideas, not MVP requirements.

## Development Rule

When requirements conflict, preserve:

1. Security
2. Correctness
3. Data/configuration safety
4. Clear UX
5. Extensibility
6. Convenience
