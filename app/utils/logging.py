"""
Logging setup for Setu.

Rule 3 (never log secrets): this module provides the app's standard
logger configuration and a `SecretRedactingFilter` that actively
scrubs *known* secret values out of every log record before it is
formatted or emitted. Callers register a password (or other
sensitive string) with `register_secret()` as soon as they have it,
so it can never reach a log line -- even indirectly, e.g. via a
captured subprocess error message that happens to echo it back.

This is a best-effort safety net, not a substitute for care at the
call site: never pass a secret to a log call directly.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import threading
from pathlib import Path

_secrets_lock = threading.Lock()
_secrets: set[str] = set()

_REDACTED = "***REDACTED***"


def register_secret(value: str | None) -> None:
    """Register a sensitive string so it is scrubbed from all future log output.

    Safe to call with None or an empty string (no-op).
    """
    if not value:
        return
    with _secrets_lock:
        _secrets.add(value)


def clear_secrets() -> None:
    """Forget all registered secrets. Mainly useful for tests."""
    with _secrets_lock:
        _secrets.clear()


def redact(text: str) -> str:
    """Scrub every registered secret out of arbitrary text.

    The logging filter below is one caller of this; it is also
    exposed directly so anything that surfaces text derived from an
    exception or subprocess output -- such as a GUI error message --
    can be scrubbed too. Rule 3 ("never log secrets") is about the
    logger specifically, but the same failure mode -- a password
    ending up somewhere it could be screenshotted or copy-pasted into
    a bug report -- applies to any surfaced text, not just log lines.
    """
    if not text:
        return text
    with _secrets_lock:
        secrets = tuple(s for s in _secrets if s)
    for secret in secrets:
        if secret in text:
            text = text.replace(secret, _REDACTED)
    return text


class SecretRedactingFilter(logging.Filter):
    """Scrubs every registered secret out of a record's message."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = redact(record.getMessage())
        record.msg = message
        record.args = ()
        return True


def get_log_dir() -> Path:
    """Return a per-user, per-app log directory (created if needed).

    Never a hardcoded, user-specific path (Rule 6) -- always derived
    from the platform's standard local-appdata location.
    """
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    log_dir = Path(base) / "Setu" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger with secret redaction always attached."""
    logger = logging.getLogger(name)
    if getattr(logger, "_setu_configured", False):
        return logger

    logger.setLevel(logging.DEBUG)
    logger.addFilter(SecretRedactingFilter())

    formatter = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    try:
        file_handler = logging.handlers.RotatingFileHandler(
            get_log_dir() / "setu.log",
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        # A non-writable log directory is a diagnostics problem, not a
        # reason to crash the app -- fall back to console-only logging.
        pass

    logger.propagate = False
    logger._setu_configured = True  # type: ignore[attr-defined]
    return logger
