"""
Safe subprocess execution.

Rule 13 (safe subprocesses): always argument arrays, never
`shell=True` without a documented, necessary reason -- this module
never sets it.

Rule 14 (no secret command-line arguments): this module deliberately
has no "secret argv" parameter. If a database's password-change
mechanism needs a secret, prefer its own safer channel (stdin via
`input=`, an environment variable the tool reads, or a supported
config API) rather than putting it in `args`, where it would be
visible to any other process inspecting the command line.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

from app.utils.logging import get_logger, register_secret

logger = get_logger(__name__)


@dataclass
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run(
    args: list[str],
    *,
    input: str | None = None,
    input_is_secret: bool = False,
    timeout: float | None = 30,
    env: dict[str, str] | None = None,
) -> ProcessResult:
    """Run a command safely and return its result.

    - `args` must be an argument list (never a shell string); this
      function never sets shell=True.
    - Pass secrets via `input` (stdin), not inside `args`, and set
      `input_is_secret=True` so the value is registered for log
      redaction before the process even runs.
    - This function never logs stdout/stderr content itself, only the
      program name and argument count -- callers must take the same
      care before surfacing captured output to the UI or a log line.
    """
    if input_is_secret and input:
        register_secret(input)

    logger.debug("Running command: %s", _describe_for_log(args))

    completed = subprocess.run(
        args,
        input=input,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        shell=False,
    )

    return ProcessResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _describe_for_log(args: list[str]) -> str:
    # Program name and argument *count* only -- never the argument
    # values, since we can't be sure none of them are sensitive (e.g.
    # a connection string with an embedded credential).
    program = args[0] if args else "<empty>"
    return f"{program} ({len(args) - 1} arg(s))"


def start(args: list[str], *, env: dict[str, str] | None = None) -> subprocess.Popen:
    """Start a long-running background process (e.g. a standalone mysqld
    during a password reset) and return the Popen handle.

    Same safety contract as `run()`: argument array only, never
    shell=True. The caller owns the returned process -- monitoring its
    output/exit and terminating it -- since "long-running" processes
    can't be captured-and-waited like `run()`'s.
    """
    logger.debug("Starting background process: %s", _describe_for_log(args))
    return subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        shell=False,
    )
