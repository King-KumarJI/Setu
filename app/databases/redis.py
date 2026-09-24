"""
Redis adapter.

A genuinely different mechanism from the other three: Redis's
`requirepass` credential is a plain line in redis.conf, read only at
startup. There is no live "temporarily weaken auth, connect, tighten
back up" dance to do here at all, because we never need to connect
to the running instance to make the change -- we stop it, edit the
credential directly in its config file (with a backup kept in case
the edit leaves it unable to start), and start it again. That means
this adapter never opens any kind of live authentication window,
unlike MySQL/MariaDB (briefly standalone, network-isolated) or
PostgreSQL/MongoDB (briefly unauthenticated, loopback-only).

IMPORTANT, stated plainly: Redis has no official Windows
distribution. Real-world Windows installs are almost always an
unofficial community port or a commercial fork such as Memurai, both
of which are redis.conf-compatible but neither of which follows a
single standardized service-registration or install-path convention.
Config-path discovery here is a best-effort regex over however the
Windows service happens to have been registered, and is the least
certain of any adapter in this project as a result -- treat it as
unverified until tested against whatever Redis-compatible service is
actually installed on the target machine.

IMPORTANT: exercised only against mocked service control and canned
command output -- there is no Redis-compatible server available in
the environment this was built in either.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from shutil import which

from app.core.detector import DetectionEngine
from app.core.models import DBMS, DetectionResult, DetectionStatus, Installation, OperationResult
from app.core.service_manager import ServiceManager
from app.databases.base import DatabaseAdapter
from app.utils import process
from app.utils.logging import get_logger, register_secret

logger = get_logger(__name__)

_CONF_PATH_PATTERN = re.compile(r'"([^"]+\.conf)"|(\S+\.conf)\b')
_REQUIREPASS_PATTERN = re.compile(r"^[ \t]*requirepass[ \t]+.*$", re.MULTILINE)


class RedisAdapter(DatabaseAdapter):
    dbms = DBMS.REDIS

    def __init__(
        self,
        service_manager: ServiceManager | None = None,
        detection_engine: DetectionEngine | None = None,
    ) -> None:
        self.service_manager = service_manager or ServiceManager()
        self.detection_engine = detection_engine or DetectionEngine()

    def detect(self) -> DetectionResult:
        return self.detection_engine.detect(DBMS.REDIS)

    def get_installations(self) -> list[Installation]:
        return self.detect().installations

    def get_version(self, installation: Installation) -> str | None:
        return installation.version

    # ------------------------------------------------------------------
    # Password change
    # ------------------------------------------------------------------
    def change_password(
        self, installation: Installation, new_password: str
    ) -> OperationResult:
        register_secret(new_password)

        if installation.status == DetectionStatus.EXECUTABLE_FOUND:
            return OperationResult(
                False, False,
                "Only the Redis client was detected, not a server installation, "
                "so the password can't be changed from here.",
            )
        if not installation.executable_path:
            return OperationResult(
                False, False,
                "No redis-server executable path was recorded for this installation.",
            )

        conf_path = self._resolve_conf_path(installation)
        if conf_path is None or not conf_path.exists():
            return OperationResult(
                False, False,
                "Couldn't determine the redis.conf location for this "
                "installation, so the password change was not attempted.",
            )

        if self._locate_sibling(installation, "redis-cli") is None:
            return OperationResult(
                False, False,
                "Couldn't locate redis-cli alongside this installation.",
            )

        try:
            original_content = conf_path.read_text()
        except OSError as exc:
            return OperationResult(
                False, False,
                f"Could not read the existing configuration ({exc}); no changes were made.",
            )

        service_name = installation.service_name
        if service_name and self.service_manager.get_service_state(service_name) == "RUNNING":
            logger.info("Stopping Redis service before editing its configuration.")
            if not self.service_manager.stop_service(service_name):
                return OperationResult(
                    False, False,
                    f"Could not stop the {service_name} service, so the "
                    "password was not changed. No changes were made.",
                )

        new_content = self._set_requirepass(original_content, new_password)
        try:
            conf_path.write_text(new_content)
        except OSError as exc:
            if service_name:
                self.service_manager.start_service(service_name)
            return OperationResult(
                False, False,
                f"Could not write the updated configuration ({exc}); the "
                "original file was left in place.",
            )

        if not service_name:
            return OperationResult(True, False, "Password changed.", restored_configuration=None)

        if self.service_manager.start_service(service_name):
            return OperationResult(True, False, "Password changed.", restored_configuration=None)

        logger.warning("Redis did not start with the new configuration; restoring the original file.")
        restore_ok = self._write_conf_and_confirm(conf_path, original_content)
        if restore_ok:
            self.service_manager.start_service(service_name)
            return OperationResult(
                False, False,
                "Redis would not start with the updated configuration, so the "
                "original file was restored and no password was changed.",
                restored_configuration=True,
            )
        return OperationResult(
            False, False,
            "Redis would not start with the updated configuration, and the "
            f"original file at {conf_path} could not be confirmed restored. "
            "Check it immediately.",
            restored_configuration=False,
        )

    def verify(self, installation: Installation, password: str) -> bool:
        register_secret(password)
        redis_cli = self._locate_sibling(installation, "redis-cli")
        if redis_cli is None:
            logger.warning("Could not locate redis-cli to verify the new password.")
            return False

        try:
            result = process.run(
                [str(redis_cli), "-h", "127.0.0.1", "PING"],
                env={**os.environ, "REDISCLI_AUTH": password},
                timeout=10,
            )
        except Exception as exc:
            logger.debug("Verification connection failed: %s", type(exc).__name__)
            return False

        # redis-cli's exit code alone is not consistently reliable across
        # versions/ports for an auth failure -- the reply text is checked
        # too (Rule 9: needs confirming against a real install).
        return result.ok and "PONG" in result.stdout

    # ------------------------------------------------------------------
    # Discovery helpers
    # ------------------------------------------------------------------
    def _resolve_conf_path(self, installation: Installation) -> Path | None:
        if not installation.service_name:
            return None
        binary_path = self.service_manager.get_service_binary_path(installation.service_name)
        if not binary_path:
            return None
        match = _CONF_PATH_PATTERN.search(binary_path)
        if not match:
            return None
        return Path(match.group(1) or match.group(2))

    def _locate_sibling(self, installation: Installation, name: str) -> Path | None:
        if installation.executable_path:
            reference = Path(installation.executable_path)
            candidate = reference.with_name(name + reference.suffix)
            if candidate.exists():
                return candidate
        located = which(name)
        return Path(located) if located else None

    # ------------------------------------------------------------------
    # Config editing
    # ------------------------------------------------------------------
    @staticmethod
    def _set_requirepass(content: str, new_password: str) -> str:
        """Replace an active `requirepass` directive, or append one if none
        exists. A commented-out example line is left untouched -- only an
        active directive is replaced, never uncommented.

        Quoted per redis.conf's own quoting rules: wrapped in double
        quotes, with an embedded double quote or backslash escaped.
        """
        escaped = new_password.replace("\\", "\\\\").replace('"', '\\"')
        line = f'requirepass "{escaped}"'
        if _REQUIREPASS_PATTERN.search(content):
            return _REQUIREPASS_PATTERN.sub(line, content, count=1)
        separator = "" if not content or content.endswith("\n") else "\n"
        return f"{content}{separator}{line}\n"

    @staticmethod
    def _write_conf_and_confirm(conf_path: Path, content: str) -> bool:
        try:
            conf_path.write_text(content)
        except OSError as exc:
            logger.warning("Could not restore redis.conf: %s", type(exc).__name__)
            return False
        try:
            return conf_path.read_text() == content
        except OSError:
            return False
