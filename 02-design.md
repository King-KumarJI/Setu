# DB Password Reset Tool — Design

## 1. Design Goal

The application should make a technically complicated operation feel simple:

> Select database → enter new password → confirm → change.

The complexity belongs in the backend, not in the user's workflow.

## 2. Main Screen

```text
┌─────────────────────────────────────────┐
│          DB Password Reset              │
│                                         │
│ Database                                │
│ [ PostgreSQL                         ▼ ]│
│                                         │
│ New Password                            │
│ [ ***************                   👁 ]│
│                                         │
│ Confirm Password                        │
│ [ ***************                   👁 ]│
│                                         │
│       [ CHANGE PASSWORD ]               │
│                                         │
│ ✓ PostgreSQL detected                   │
└─────────────────────────────────────────┘
```

## 3. Status States

### Detected

```text
✓ PostgreSQL detected
Version: 16
Server: Running
```

### Client only

```text
⚠ PostgreSQL executable detected
Server status could not be confirmed
```

### Not detected

```text
✕ PostgreSQL not detected
```

### Multiple installations

```text
Multiple PostgreSQL installations detected.

○ PostgreSQL 15
○ PostgreSQL 16
○ PostgreSQL 17

[Continue]
```

## 4. Interaction Flow

```text
Application start
       ↓
Detect databases
       ↓
Populate dropdown
       ↓
User selects DB
       ↓
Enter password
       ↓
Validate
       ↓
Resolve installation/server
       ↓
Execute adapter operation
       ↓
Verify
       ↓
Restore temporary configuration
       ↓
Show result
```

## 5. UX Rules

- No unnecessary technical terminology.
- No manual path entry in the normal workflow.
- Passwords are masked by default.
- Provide show/hide controls.
- Never display passwords in status messages.
- Disable the action button while an operation is running.
- Show progress for operations that take time.
- Errors should explain what the user can do next.

## 6. Visual Style

Recommended:

- clean desktop utility
- restrained colors
- strong contrast
- consistent spacing
- keyboard accessibility
- native-feeling controls
- no unnecessary animations

## 7. Error UX

Avoid raw tracebacks.

Instead of:

```text
subprocess.CalledProcessError: ...
```

show:

```text
Password change failed.

PostgreSQL was detected, but the server could not be reached.
Check that the PostgreSQL service is running and try again.
```

Developer logs can contain diagnostic information, but never secrets.

## 8. Accessibility

- Every input must have a label.
- Keyboard navigation must work.
- Status should not rely only on color.
- Error messages should be readable by assistive technologies.
