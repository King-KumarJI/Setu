# Product Requirements Document — DB Password Reset Tool

## 1. Product Summary

A Windows desktop utility that detects locally installed database systems and provides a single simple interface for changing an administrator-controlled database password.

## 2. Problem

Developers frequently forget local database passwords and then have to manually:

- locate installation directories
- find executables
- identify services
- inspect authentication configuration
- perform database-specific recovery steps
- restore configuration
- verify connectivity

These workflows differ significantly between DBMS products.

## 3. Product Vision

Hide the operating-system and database-specific complexity behind a consistent UI.

The desired user experience is:

> Select → Enter → Confirm → Change.

## 4. Target Users

Primary:

- software developers
- MCA/CS students
- local development users
- system/database administrators

The tool is intended for systems the user is authorized to administer.

## 5. MVP Scope

### Supported platform

Windows.

### DBMS

Full initial support:

- MySQL
- PostgreSQL

Detection/architecture support:

- MongoDB
- MariaDB
- Redis

### UI

Required:

- DBMS dropdown
- new password
- confirm password
- show/hide password
- change button
- status/error area

## 6. Functional Requirements

### FR-01 — Detect DBMS

The application shall detect database executables using environment/PATH information and additional Windows discovery mechanisms.

### FR-02 — Identify Installation

The application shall identify the executable and, where possible, installation/version information.

### FR-03 — Detect Server State

The application shall distinguish executable availability from server/service availability.

### FR-04 — Multiple Installations

The application shall not silently choose between multiple detected installations.

### FR-05 — Validate Password

The application shall reject empty or mismatched password fields.

### FR-06 — Change Password

The selected adapter shall perform the supported administrative password-change procedure.

### FR-07 — Verify

The application should verify the new credentials after a successful operation where technically possible.

### FR-08 — Configuration Safety

Temporary configuration changes must be backed up and restored.

### FR-09 — Secret Handling

Passwords must never be logged or persisted.

### FR-10 — User Feedback

The application shall provide actionable success and failure messages.

## 7. Non-Functional Requirements

### Security

- No credential extraction.
- No password dumping.
- No unauthorized remote-access features.
- No persistent password storage.
- Safe subprocess execution.

### Reliability

- Graceful failure.
- Configuration restoration.
- Clear state reporting.

### Maintainability

- Adapter architecture.
- Type hints.
- Unit tests.
- Separation of concerns.

### Usability

- Minimal UI.
- Beginner-friendly messages.
- Keyboard accessible.

## 8. Out of Scope for MVP

- Remote database password management.
- Credential vault.
- Password recovery by extracting the old password.
- Automated exploitation of authentication weaknesses.
- Cloud database management.
- Linux/macOS support.
- Advanced database administration.

## 9. Success Criteria

The MVP is successful when a user can:

1. Launch the application.
2. See locally detected DBMS software.
3. Select a supported database.
4. Enter and confirm a new password.
5. Perform the supported password-change workflow.
6. Receive clear success/failure feedback.
7. Confirm that the new credentials work.

## 10. Risks

### DBMS differences

Each DBMS has a different authentication architecture.

Mitigation: adapter-specific implementations.

### PATH limitations

A database may be installed without its executable being in PATH.

Mitigation: secondary detection mechanisms.

### Multiple versions

Several installations may coexist.

Mitigation: explicit installation selection.

### Privileges

Administrative operations may require elevation.

Mitigation: detect and clearly request appropriate privileges.

### Configuration damage

Temporary recovery changes can leave a system insecure if not restored.

Mitigation: backup, transactional workflow, restoration verification.
