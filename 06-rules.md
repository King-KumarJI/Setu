# DB Password Reset Tool — Engineering Rules

## Rule 1 — Security First

The application is for systems the user is authorized to administer.

Never add credential theft, password extraction, or unauthorized-access functionality.

## Rule 2 — Never Retrieve the Old Password

The product changes/resets a password through legitimate administrative mechanisms.

It does not attempt to discover the previous password.

## Rule 3 — Never Log Secrets

Passwords, tokens, connection strings containing secrets, and authentication material must never appear in logs.

## Rule 4 — Never Persist Passwords

Do not save passwords to:

- files
- SQLite databases
- configuration files
- environment files
- crash reports
- analytics

## Rule 5 — Do Not Trust PATH Alone

PATH is a discovery mechanism, not proof that a database server is installed or running.

Always distinguish client executable, server installation, service, and running/accessibility state.

## Rule 6 — No Hardcoded User Paths

Never assume:

```text
C:\Program Files\...
```

or another user-specific location is the only valid installation path.

## Rule 7 — Adapters Own DB-Specific Logic

MySQL logic belongs in the MySQL adapter.

PostgreSQL logic belongs in the PostgreSQL adapter.

Do not mix DBMS-specific behavior into the GUI.

## Rule 8 — No Giant Conditional

Avoid:

```python
if mysql:
    ...
elif postgres:
    ...
elif mongo:
    ...
```

Use the adapter interface.

## Rule 9 — Do Not Invent Commands

Database commands and recovery workflows must be based on documented behavior and tested against the relevant DBMS/version.

## Rule 10 — Protect Configuration

Before modifying a configuration file:

1. Create a backup.
2. Validate the backup.
3. Make the smallest necessary change.
4. Perform the operation.
5. Restore the original configuration.
6. Verify restoration.

## Rule 11 — Fail Safely

If restoration fails, tell the user immediately and provide enough diagnostic information to recover safely.

Never hide a failed restoration.

## Rule 12 — Explicit User Action

Do not silently change passwords, authentication configuration, or services.

The password-change operation begins only after explicit user action.

## Rule 13 — Safe Subprocesses

Prefer:

```python
subprocess.run(["program", "argument"], ...)
```

over shell command strings.

Avoid `shell=True` unless there is a documented, necessary reason.

## Rule 14 — No Secret Command-Line Arguments

Do not pass passwords through command-line arguments when that would expose them through process inspection.

Use safer supported mechanisms where available.

## Rule 15 — GUI Stays Simple

The GUI should not expose unnecessary database internals.

Advanced diagnostics can exist behind a separate diagnostic area if needed.

## Rule 16 — Errors Must Be Actionable

A user should understand:

- what failed
- which database was involved
- whether configuration was restored
- what they can try next

## Rule 17 — Never Claim Success Without Verification

If verification is possible, perform it.

Do not display:

```text
Password changed successfully
```

when the operation was not actually confirmed.

## Rule 18 — Tests Before Expansion

Do not add another DBMS until the adapter architecture and existing implementations remain stable.

## Rule 19 — Platform Isolation

Windows-specific service and filesystem code should be isolated so future Linux/macOS support does not require rewriting database adapters.

## Rule 20 — Documentation Is Part of the Product

Every supported DBMS must document:

- detection method
- supported versions
- authentication assumptions
- required privileges
- limitations
- verification method

## Rule 21 — Preserve Existing Configuration

Never delete unrelated configuration.

Only modify the minimum required settings.

## Rule 22 — Prefer Reversible Operations

When an operation can be made reversible, make it reversible.

## Rule 23 — No Silent Network Behavior

The MVP is local-first.

Do not introduce remote database operations or external telemetry without an explicit product requirement.

## Rule 24 — Keep the Architecture Extensible

New DBMS support should require adding an adapter rather than rewriting the core application.

## Rule 25 — When Uncertain, Stop

If the application cannot safely determine the database state or required procedure, do not guess.

Report the ambiguity and require an explicit supported path.
