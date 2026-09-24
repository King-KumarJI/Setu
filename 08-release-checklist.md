# DB Password Reset Tool — Release Checklist

This is the Phase 7 "Release checklist" deliverable itself, and the
checklist to actually run through before handing a build of Setu to
anyone else — including the user, on their own other machines.

Phase 7's exit criterion is: **"A clean Windows machine can
install/run the application with documented prerequisites."** Nothing
below is checked off automatically; every box here requires actually
doing the thing on a real Windows machine, since this project has been
developed in a Linux sandbox with no PySide6, no `sc`-backed Windows
service control, and no real DBMS server available at any point (see
`07-hardening-review.md` Section 1 and Section 9). This checklist
exists specifically so that gap gets closed deliberately, once, rather
than discovered by a confused user.

## 1. Before building

- [ ] `git status` is clean, or every uncommitted change is
      intentional and reviewed.
- [ ] Full test suite passes: `pytest` → currently 137 tests, all
      passing as of the Phase 6 close. `packaging/build.ps1` also runs
      this as a build gate and refuses to build on a failure, but
      confirm it manually first too.
- [ ] Version number is consistent in three places: `pyproject.toml`
      (`[project] version`), `packaging/version_info.txt`
      (`filevers`/`prodvers`/`FileVersion`/`ProductVersion` — all four
      fields), and this checklist's own expectations. They currently
      all say `0.1.0`.
- [ ] `07-hardening-review.md`'s open items (Section 9) have been
      re-read. None of them are release-blocking on their own, but
      "no live-database verification anywhere" and "GUI never
      launched" are both closed out by Sections 2 and 3 below, and
      should not still be open when this checklist is signed off.

## 2. Build

- [ ] Run `packaging\build.ps1` on the actual target Windows machine
      (PowerShell, not WSL/Linux — see the script's own docstring for
      why). Confirm it completes and produces `dist\Setu.exe`.
- [ ] **This PowerShell script has never been executed anywhere** —
      it was written and reviewed by eye in a Linux sandbox with no
      `pwsh`/`powershell` available to even syntax-check it. Treat the
      first real run of `build.ps1` as a test of the script itself,
      not just of the app; fix and re-run if it errors before
      proceeding.
- [ ] Confirm `dist\Setu.exe`'s file properties (right-click → 
      Properties → Details in Explorer) show the expected product
      name, file description, and version — this is `version_info.txt`
      actually taking effect, not just present in the repo.
- [ ] Confirm the `.exe`'s icon in Explorer matches
      `app/resources/icon.ico` (a teal rounded-square bridge icon) —
      this is the PyInstaller `icon=` argument actually taking effect.

## 3. Smoke test on a clean machine

"Clean" means: no project `.venv` on `PATH`, ideally a separate
Windows user account or VM that has never had Python/PySide6
installed system-wide, so this genuinely tests what Phase 7's exit
criterion asks for.

- [ ] Copy only `dist\Setu.exe` to the clean machine (not the whole
      repo) and double-click it. It should launch with no console
      window (this is a `windowed`/`console=False` build) and no
      "missing DLL"/"missing module" errors.
- [ ] Launch it **not** elevated (a normal double-click). Confirm the
      non-elevated warning banner (`app/utils/elevation.py`,
      `MainWindow._check_elevation`) appears before detection starts.
      This exercises `IsUserAnAdmin()` for the first time anywhere —
      `07-hardening-review.md` Section 6 flagged this as unverified.
- [ ] Right-click → "Run as administrator" and relaunch. Confirm the
      warning banner does *not* appear.
- [ ] With at least one real DBMS installed on that machine (see
      Section 4 — do not skip straight to a password change without
      this), confirm detection correctly reports
      installed/running/not-found for each of MySQL, PostgreSQL,
      MariaDB, MongoDB, and Redis, matching what's actually installed.
- [ ] Click through the full window: DBMS dropdown, installation
      picker (only when multiple installations of one DBMS exist),
      password fields with the show/hide toggle, Change Password
      button, status text. Confirm nothing looks clipped, mislabeled,
      or crashes — this is the first time the built GUI has been seen
      at all (`07-hardening-review.md` Section 9, item 2).

## 4. Real-database verification (the big one)

Every adapter's `change_password()` has been reviewed and unit-tested
against **mocked** subprocess calls only — never against an actual
running server. This is the single largest gap called out in
`07-hardening-review.md` Section 1, and it does not close itself by
building an executable. Before trusting Setu with a credential that
matters:

- [ ] Install a real, disposable/test instance of each DBMS on a
      throwaway Windows VM (not a machine with data you care about).
- [ ] For each DBMS, set a known password, then use Setu to reset it
      to a different known password, then confirm you can actually
      connect with the new password (and that the old one no longer
      works).
- [ ] For each DBMS, confirm the "verified" vs "unverified" and
      "restored" vs "not restored" states in the status text match
      reality — deliberately interrupt one run if you can (e.g. kill
      the standalone `mysqld`/`mongod` process mid-operation, or
      revoke write access to `pg_hba.conf`) and confirm Setu reports
      the failure honestly rather than claiming success (Rule 17).
- [ ] MongoDB specifically: confirm the target instance's admin
      username really is `root` before testing it, or the reset will
      fail at the `updateUser` step — this is a known, documented
      limitation (`07-hardening-review.md` Section 9, item 4), not a
      bug to chase during this checklist.

## 5. Distribution

- [ ] Decide how `Setu.exe` will actually reach the user's other
      machines (a file share, a USB drive, email — this project has no
      release infrastructure of its own; Rule 23 — no silent network
      behavior — means Setu itself will never phone home to
      distribute or update itself).
- [ ] **Unsigned executable, expect SmartScreen/antivirus friction.**
      `Setu.exe` is not code-signed (no certificate has been part of
      this project). Windows SmartScreen and some antivirus products
      will likely flag or warn about an unrecognized/unsigned
      executable, especially one built with PyInstaller (a common
      false-positive trigger due to how PyInstaller bundles a Python
      interpreter). This is expected, not a build failure — document
      it for whoever runs the `.exe`, and consider code-signing as
      future work if wider distribution is ever planned.
- [ ] Optionally record a SHA-256 checksum of the built `Setu.exe`
      (`Get-FileHash dist\Setu.exe -Algorithm SHA256` in PowerShell)
      alongside wherever it's distributed, so a recipient can confirm
      they received an unmodified copy.

## 6. Sign-off

- [ ] Every box above is checked, on a real Windows machine, not
      assumed from reading this document.
- [ ] Record here: build date, `pyproject.toml` version, and who ran
      this checklist.

```text
Build date:
Version:
Checked by:
```
