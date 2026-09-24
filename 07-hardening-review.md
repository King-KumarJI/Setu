# DB Password Reset Tool — Phase 6 Hardening Review

## 1. Purpose and Methodology

This document records the Phase 6 review against `06-rules.md`, tasks
performed, findings, fixes applied, and what remains open.

Methodology was static code review (reading every code path against
each rule) plus targeted, executable regression tests
(`app/tests/test_secrets_regression.py`, `app/tests/test_elevation.py`)
rather than manual reasoning alone — a finding was only closed once a
test could fail if the behavior regressed.

**Standing limitation, stated plainly (Rule 25):** no real MySQL,
MariaDB, PostgreSQL, MongoDB, or Redis server has been available in
this development environment at any point. Every adapter's
orchestration logic (service stop/start, standalone-instance startup,
the actual `ALTER USER`/`updateUser`/`requirepass` mechanism) is
verified by static review, unit tests against mocked subprocess calls,
and matching the DBMS's own documented recovery procedure — never by
running it against a live server. This is the single largest
unresolved verification gap in the project and should be the first
thing done on the real Windows machine, against a real installation of
each DBMS, before this tool is used on anything the user cares about.

## 2. Security Review (Rule 1, Rule 2)

- No code path retrieves, decodes, or attempts to discover an
  existing password. Every adapter's `change_password()` sets a new
  password through the DBMS's own documented administrative recovery
  mechanism (MySQL/MariaDB `--init-file`, PostgreSQL a temporary
  `pg_hba.conf trust` rule + `ALTER ROLE`, MongoDB a `--noauth`
  restart + `updateUser`, Redis a direct `requirepass` edit).
- No credential-theft, keylogging, or unauthorized-access code exists
  anywhere in the codebase.
- Finding, addressed in this phase (Task 31): nothing previously
  checked whether the process was running elevated before attempting
  a service-control or protected-config operation, which meant a
  standard-user run of Setu could fail confusingly partway through
  (see Section 6).

## 3. Error Handling Review (Rule 11, Rule 16)

- Every adapter's `change_password()` returns an `OperationResult`
  with distinct `success` and `verified` fields; nothing collapses
  "the operation ran" into "the operation is confirmed correct."
- PostgreSQL's `_restore_hba()` and Redis's config rollback both read
  the restored file back and compare, rather than assuming a write
  succeeded; MySQL/MariaDB restore original service state via
  `ServiceManager`, which itself polls actual `sc query` state rather
  than assuming a start/stop command was obeyed.
- `presentation.py`'s `operation_result_text()` distinguishes four
  outcomes (success+verified, success+unverified, failure with
  restoration confirmed, failure with restoration unconfirmed) so the
  user is never told plain "success" when verification could not run,
  satisfying Rule 17 at the GUI layer as well as the adapter layer.
- No new findings this phase; this area was built with these
  constraints in mind from Phase 3 onward and is re-confirmed here
  rather than newly hardened.

## 4. Secret-Handling Review (Rule 3, Rule 4, Rule 14)

### 4.1 Logging (Rule 3)

- Audited every `logger.*` call site in `app/` (excluding tests):
  every one logs static text, a DBMS/service name, or
  `type(exc).__name__` — never a raw secret or a raw exception message
  that could echo one back.
- **Finding, fixed this phase:** `app/gui/presentation.py`'s
  `friendly_error()` generic-exception fallback
  (`f"Something went wrong: {exc}"`) was not covered by
  `SecretRedactingFilter`, since that filter only wraps logger
  handlers, not arbitrary GUI-facing strings. A password is never
  passed into that fallback by any current code path, but nothing
  structurally prevented a future exception from carrying one through.
  Fixed by extracting the filter's scrubbing logic into a public
  `redact(text: str) -> str` function in `app/utils/logging.py`, and
  wrapping both `friendly_error()`'s fallback and all three
  `operation_result_text()` return paths in it. This is defense in
  depth, not a sign a leak was ever observed.

### 4.2 Persistence (Rule 4)

- Grepped for every file write in `app/`: the only writes are (a) the
  four adapters' one-shot secret-bearing temp files, and (b) each
  adapter's own configuration file when that write is the DBMS's own
  designed-for-this mechanism (see 4.3). Nothing in Setu's own storage
  — no SQLite database, no settings file, no crash report, no
  analytics payload — ever receives a password.
- **Temp-file cleanup audit (Task 30), now backed by a regression
  test:** every secret-bearing temp file
  (`mysql.py`/`mariadb.py`'s `--init-file` and
  `--defaults-extra-file`, `postgresql.py`'s `.pgpass`-format file,
  `mongodb.py`'s mongosh script) is created via a `_write_*` helper
  that cleans up on its own construction failure, and every call site
  wraps the file's use in `try/finally` so `_delete_temp_file()` runs
  whether the subsequent subprocess call succeeds, fails, or raises.
  `app/tests/test_secrets_regression.py` now exercises all four
  helpers directly: it confirms the secret really was written (so the
  test would fail loudly if a future change stopped embedding it),
  runs the adapter's own cleanup call, and asserts the file is gone
  and no stray `setu_*` file is left anywhere in the OS temp
  directory.
- **Windows temp-file ACL caveat, stated explicitly:** every temp-file
  helper calls `os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)`
  immediately after creation. On POSIX this restricts the file to the
  owner. On Windows, `os.chmod`'s effect on NTFS ACLs is much weaker —
  it can clear the read-only attribute bit but does not rewrite the
  file's ACL/DACL the way `icacls` would, so this call should not be
  read as "this file is provably inaccessible to other Windows
  users." In practice the file lives in `tempfile.gettempdir()`,
  which resolves to the invoking user's own `%TEMP%`
  (`C:\Users\<user>\AppData\Local\Temp`) — a location NTFS already
  restricts to that user and Administrators by default folder
  inheritance, independent of anything Setu does. The mitigation is
  real but comes from Windows' own default ACL on that path, not from
  the `os.chmod` call; this should be verified with `icacls` on the
  actual target machine rather than assumed, and is listed as an open
  item in Section 7.

### 4.3 Redis `requirepass` is not a Rule 4 violation

Redis's adapter (`app/databases/redis.py`) writes the new password
directly into `redis.conf`'s `requirepass` directive while the service
is stopped. This is flagged here explicitly because, read out of
context, "the adapter writes a password to a file" looks like it might
be exactly what Rule 4 forbids. It is not: Rule 4 is about **Setu's
own storage** — the application must not save a password anywhere in
its own state (its config, its database, its logs, its crash reports).
`redis.conf`'s `requirepass` is the **target database's own**
persistent authentication configuration, in the location Redis itself
is designed to read it from on every startup; writing there is the
entire point of the operation, in the same way MySQL's `ALTER USER`
statement durably changes MySQL's own `mysql.user` table. No other
adapter needs an equivalent write because MySQL/MariaDB/PostgreSQL/
MongoDB all store credentials inside the server's own database rather
than in a plaintext config file — Redis is simply the one DBMS here
whose "durably store the new credential" step is a file write instead
of a SQL statement.

### 4.4 Command-line arguments (Rule 14)

Re-confirmed: no adapter passes a password as a bare CLI argument.
MySQL/MariaDB use `--defaults-extra-file`; PostgreSQL uses stdin
(`psql -f -`) for the `ALTER ROLE` statement and `.pgpass` for
`verify()`; MongoDB writes the `updateUser`/auth call into a temp `.js`
file passed via `--file`; Redis uses the `REDISCLI_AUTH` environment
variable for `verify()`, never `-a`.

## 5. Configuration Backup/Restore Review (Rule 10, Rule 21, Rule 22)

- PostgreSQL is the only adapter that opens a live "trust window": it
  prepends one narrowly-scoped rule
  (`host all postgres 127.0.0.1/32 trust`) to `pg_hba.conf`, reloads,
  runs the `ALTER ROLE`, and unconditionally restores the original
  file content in a `finally` block, verified by reading the file back
  — never leaving unrelated lines touched (Rule 21) and never leaving
  the trust rule in place if anything after the reload fails (Rule
  22).
- Redis's adapter backs up the original `redis.conf` content in
  memory before editing, and if the service fails to start with the
  new config, rolls back to the original content and retries the
  start — this is the Rule 22 "prefer reversible" pattern applied to a
  DBMS with no live trust-window mechanism to open in the first place.
- MySQL/MariaDB/MongoDB don't edit a live server's configuration file
  at all — they run a temporary, standalone, non-networked instance
  of the server binary against the real data directory for the
  instant it takes to apply the change, then shut it down and restore
  the Windows service to whatever state it was in beforehand. "The
  configuration to restore" for these three is the **service's
  running/stopped state**, not a config file — restoration is done via
  `ServiceManager`, which polls actual `sc query` output rather than
  assuming a start/stop command succeeded.
- No findings this phase; each adapter's restore path was designed
  and tested (against mocked I/O) against these rules from the outset
  and is re-confirmed rather than newly changed.

## 6. Permission/Elevation Handling (Task 31 — new this phase)

Added `app/utils/elevation.py`:

- `is_elevated() -> bool | None` — `True`/`False` on Windows via the
  documented `ctypes.windll.shell32.IsUserAnAdmin()` API (Rule 9: no
  undocumented mechanism); `None` on non-Windows or if the check
  itself fails, which callers must treat as "unknown, don't block on
  it" rather than guessing either way (Rule 25).
- `elevation_warning() -> str | None` — a user-facing message only on
  a **confirmed** `False`; stays silent on `None` rather than nagging
  with a warning that might be wrong.
- Wired into `MainWindow`: a warning label is shown above the form,
  before detection even starts, when the process is confirmedly not
  elevated. This surfaces the problem before the user has typed a
  password, rather than as a confusing access-denied failure partway
  through a service-stop call (Rule 11/16).
- `app/tests/test_elevation.py` (8 tests) exercises every branch —
  elevated, not elevated, and check-failed — by monkeypatching
  `ctypes.windll` on this non-Windows development environment, since
  `ctypes.windll` doesn't exist here to call for real.
- **Not yet verified:** whether `IsUserAnAdmin()` actually reports
  correctly and whether the GUI warning renders as intended can only
  be confirmed by running the built application on the real Windows
  machine, both elevated and not — PySide6 could not be installed in
  this sandbox (see Section 7).

## 7. Logging Review (Rule 3)

Covered in Section 4.1. No further findings beyond the
`presentation.py` gap already described and fixed.

## 8. Regression Tests (this phase)

- `app/tests/test_secrets_regression.py` (5 tests, new): a full
  `password_manager.change_password()` call against `MockAdapter` —
  the same entry point the GUI uses — with logging captured, asserting
  the plaintext password appears nowhere in captured output; plus one
  test per adapter's secret-bearing temp-file helper, asserting the
  file is gone and no `setu_*` file is left in the OS temp directory
  after the adapter's own cleanup call runs.
- `app/tests/test_elevation.py` (8 tests, new): covered in Section 6.
- Full suite run as the close of this phase:

  ```text
  137 passed in 0.45s
  ```

  (124 tests existed at the start of Phase 6; +8 elevation, +5
  secrets-regression = 137. Zero regressions, zero skips, zero
  failures.)

## 9. Open Items Carried Forward

These are explicitly **not** closed by this review and should be
addressed before the tool is used against a production database:

1. **No live-database verification anywhere** (Section 1). Every
   adapter must be exercised against a real installed MySQL, MariaDB,
   PostgreSQL, MongoDB, and Redis server on the actual Windows target
   machine before this tool is trusted with a real credential.
2. **GUI never launched.** PySide6 could not be installed in this
   development sandbox (network/bandwidth-limited proxy; three
   attempts, largest reaching an 80MB partial download before timing
   out). `app/gui/main_window.py` and `app/gui/presentation.py` are
   verified by `py_compile`/`ast.parse` and, for `presentation.py`,
   by unit tests — but the window has never actually been opened,
   clicked through, or visually reviewed. This must happen on the
   real machine.
3. **Windows temp-file ACLs** (Section 4.2) — verify with `icacls`
   on the real machine rather than relying on `%TEMP%`'s default
   inheritance.
4. **MongoDB's hardcoded admin username** (`_ADMIN_USERNAME = "root"`
   in `mongodb.py`) is a convention-based assumption, not something
   MongoDB enforces. If the real target instance's admin user has a
   different name, the reset will fail at the `updateUser` step. This
   is a known, documented limitation, not a silent bug — but it's
   real and should be surfaced to the user or made configurable in a
   later phase.
5. **Elevation check unverified on real Windows** (Section 6).

## 10. Summary

Every Phase 6 task (security review, error-handling review,
secret-handling review, configuration backup/restore review,
permission/elevation handling, logging review, regression tests) has
been performed, and its exit criterion — "No secrets appear in logs or
persistent files" — is now backed by an executable regression test
(`test_secrets_regression.py`) in addition to the manual review, not
just asserted from reading the code. One real gap was found and fixed
(the `presentation.py` redaction gap, Section 4.1); everything else
reviewed was already correctly built and is re-confirmed here rather
than newly changed. The project is not yet ready for use against a
production database — Section 9's open items, especially live-database
verification and an actual GUI launch, are the required next steps,
and are appropriately scoped to happen on the real Windows machine
rather than this development sandbox.
