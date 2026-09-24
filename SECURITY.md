# Security Policy

Setu is an administrator-elevated tool that detects local database
installations and resets local database passwords. Because it runs
with elevated privileges and touches credentials, security reports
get priority attention.

## Reporting a vulnerability

**Please do not open a public GitHub issue for security
vulnerabilities.**

Instead, report privately using GitHub's "Report a vulnerability"
button under this repository's **Security** tab (Security Advisories
→ Report a vulnerability). This opens a private draft advisory
visible only to maintainers until a fix is ready.

If that isn't available to you, email the maintainer directly (see
the profile on the GitHub repository for a current contact address)
with:

- A description of the issue and its potential impact
- Steps to reproduce, or a proof of concept
- The Setu version and Windows version you tested against

## What to expect

- Acknowledgement of your report within 5 business days
- An initial assessment (confirmed / not applicable / needs more
  info) within 10 business days
- Credit in the release notes once a fix ships, unless you ask to
  stay anonymous

## Scope

In scope: anything that lets Setu leak a database credential it
handles, escalate privileges beyond what the signed-in administrator
already has, execute unintended commands, or write secrets somewhere
they'd persist (logs, temp files, crash dumps) outside the deliberate,
short-lived temp files it already deletes after use.

Out of scope: vulnerabilities in the underlying database engines
themselves (MySQL, PostgreSQL, MariaDB, MongoDB, Redis) — report
those upstream. Also out of scope: issues that require the attacker
to already have Administrator rights on the machine, since that's the
same trust level Setu itself requires to operate.

## Design notes relevant to security review

Setu does not make network calls, does not phone home, and does not
collect telemetry — all detection and password-reset operations are
local. Temporary files used to pass credentials to database CLIs
(init files, client-defaults files, `.pgpass`, script files) are
written with the most restrictive permissions the OS allows and
deleted immediately after use; see `07-hardening-review.md` in this
repository for the fuller internal review this was built against,
including the known Windows limitation that `os.chmod` cannot express
true owner-only POSIX permissions on that platform.
