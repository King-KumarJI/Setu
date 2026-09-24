# DB Password Reset Tool — Architecture

## 1. Purpose

A Windows-first desktop utility that detects locally installed database systems and provides a simple GUI for changing an administrator-controlled database password.

The GUI stays intentionally simple. Database-specific behavior is isolated behind adapters.

## 2. High-Level Architecture

```text
┌──────────────────────────────┐
│           PySide6 GUI        │
│  DB dropdown                 │
│  New password                │
│  Confirm password            │
│  Change Password             │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│      Password Manager        │
│ validation / orchestration   │
└──────────────┬───────────────┘
               │
       ┌───────┴────────┐
       ▼                ▼
 Detection Engine   Service Manager
       │
       ▼
┌──────────────────────────────┐
│      Database Adapters       │
│ MySQL / PostgreSQL / MongoDB │
│ MariaDB / Redis              │
└──────────────────────────────┘
```

## 3. Project Structure

```text
app/
├── main.py
├── gui/
│   └── main_window.py
├── core/
│   ├── detector.py
│   ├── password_manager.py
│   ├── service_manager.py
│   ├── verifier.py
│   └── models.py
├── databases/
│   ├── base.py
│   ├── mysql.py
│   ├── postgresql.py
│   ├── mongodb.py
│   ├── mariadb.py
│   └── redis.py
├── utils/
│   ├── process.py
│   ├── paths.py
│   └── logging.py
└── tests/
```

## 4. Detection Strategy

Detection should use multiple signals:

1. Windows PATH / environment variables.
2. Executable discovery using `shutil.which()`.
3. Windows Services.
4. Version information from the executable when safely available.
5. Known configuration locations only as secondary discovery, never as a single hardcoded assumption.

A detection result should distinguish:

- executable found
- installation identified
- server/service found
- server running
- server accessible

Finding a client executable must not automatically mean that a database server is running.

## 5. Adapter Pattern

Every DBMS implements a common interface.

```python
class DatabaseAdapter:
    def detect(self):
        ...

    def get_installations(self):
        ...

    def get_version(self):
        ...

    def change_password(self, new_password):
        ...

    def verify(self, password):
        ...
```

Adapters own database-specific commands and authentication behavior.

## 6. Safety Boundaries

The tool operates only on systems the user administers.

It must never:

- extract existing passwords
- dump credentials
- attempt credential theft
- silently bypass remote authentication
- transmit credentials
- persist passwords

If a supported recovery procedure requires a temporary authentication configuration change, the original configuration must be backed up and restored.

## 7. Process Execution

Use `subprocess.run()` with argument arrays rather than unsafe shell string concatenation.

Never include passwords in command-line arguments when the database provides a safer mechanism.

## 8. Extensibility

Adding a DBMS should require:

1. New adapter.
2. Detection definitions.
3. Service/configuration logic if needed.
4. Tests.
5. GUI registration.

The GUI should not need database-specific conditional logic.
