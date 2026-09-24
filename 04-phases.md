# DB Password Reset Tool — Development Phases

## Phase 0 — Foundation

### Goal

Create a clean, runnable project skeleton.

### Tasks

- Python project setup.
- PySide6 dependency.
- Directory structure.
- Logging.
- Configuration/model classes.
- Base database adapter interface.
- Test framework.

### Exit Criteria

- Application launches.
- Tests run.
- Architecture is separated into GUI/core/database modules.

---

## Phase 1 — Detection Engine

### Goal

Detect locally available database software.

### Tasks

- PATH scanning.
- `shutil.which()` integration.
- Executable metadata.
- Windows Service discovery.
- Multiple-installation detection.
- Basic version detection.

### Exit Criteria

The application can correctly distinguish:

- not detected
- executable detected
- server/service detected
- running
- multiple installations

---

## Phase 2 — GUI MVP

### Goal

Build the minimal user interface.

### Tasks

- DBMS dropdown.
- New password field.
- Confirm password field.
- Show/hide password.
- Change Password button.
- Status area.
- Error dialogs.

### Exit Criteria

The GUI works with mocked adapters without requiring real password changes.

---

## Phase 3 — MySQL Adapter

### Goal

Implement a tested MySQL workflow.

### Tasks

- Detect installation.
- Resolve relevant executable/server.
- Determine supported authentication state.
- Implement the legitimate administrative password-change workflow.
- Verify credentials.
- Handle failure safely.

### Exit Criteria

Tested against supported local MySQL configurations.

---

## Phase 4 — PostgreSQL Adapter

### Goal

Implement PostgreSQL support.

### Tasks

- Detect PostgreSQL.
- Identify server/service.
- Resolve configuration.
- Determine authentication method.
- Implement supported local administrative recovery/change workflow.
- Backup/restore temporary configuration changes if required.
- Verify the new password.

### Exit Criteria

Tested against supported local PostgreSQL versions/configurations.

---

## Phase 5 — Secondary DBMS

Implement:

- MariaDB
- MongoDB
- Redis

Each requires its own authentication model and must not reuse assumptions from MySQL/PostgreSQL.

---

## Phase 6 — Hardening

### Tasks

- Security review.
- Error handling review.
- Secret-handling review.
- Configuration backup/restore tests.
- Permission/elevation handling.
- Logging review.
- Regression tests.

### Exit Criteria

No secrets appear in logs or persistent files.

---

## Phase 7 — Packaging

### Tasks

- Build Windows executable.
- Installer or portable package.
- Application icon.
- Version metadata.
- README.
- Release checklist.

### Exit Criteria

A clean Windows machine can install/run the application with documented prerequisites.

---

## Phase 8 — Future Platforms

Only after Windows support is stable:

- Linux
- macOS

Platform-specific service and filesystem logic should remain isolated from the database adapters where practical.
