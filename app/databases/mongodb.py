"""
MongoDB adapter.

A genuinely different auth model from MySQL/MariaDB/PostgreSQL, per
MongoDB's own documented "Resync a User" / password-reset procedure:
authentication is an all-or-nothing, startup-time flag
(security.authorization), not something reloadable live like
PostgreSQL's pg_hba.conf, and not something a single self-contained
--init-file can apply like MySQL/MariaDB. The documented recovery is:
stop mongod, restart it standalone with authorization disabled and
bound ONLY to 127.0.0.1 (MongoDB's own docs call out binding to
localhost during this window), change the password, shut down
cleanly, restart normally.

Real limitation worth stating plainly: unlike MySQL's `root` or
PostgreSQL's `postgres`, MongoDB has no OS-installer-guaranteed
administrative username -- whoever set up the deployment chose it.
This adapter assumes the conventional name "root" (the same
convention MySQL/MariaDB use, and one MongoDB's own tutorials use as
a placeholder). If a real deployment used a different admin username,
changeUserPassword fails cleanly with "user not found" rather than
guessing or acting on the wrong account.

Password-bearing scripts are always written to a temporary file and
passed to mongosh via --file (a real file path, not stdin) rather
than embedded in a command-line argument (Rule 14) -- mongosh's
support for reading a script from stdin was not something I could
confirm without a real mongosh to test against, so this uses the
option that is unambiguously documented and supported.

IMPORTANT: exercised only against mocked service control and canned
command output -- there is no MongoDB server available in the
environment this was built in. Rule 9 requires verification against a
real local MongoDB installation before this is trusted.
"""
from __future__ import annotations

import os
import queue
import re
import stat
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from shutil import which

from app.core.detector import DetectionEngine
from app.core.models import DBMS, DetectionResult, DetectionStatus, Installation, OperationResult
from app.core.service_manager import ServiceManager
from app.databases.base import DatabaseAdapter
from app.utils import process
from app.utils.logging import get_logger, register_secret

logger = get_logger(__name__)

_CONFIG_ARG_PATTERN = re.compile(r'(?:--config|-f)\s+"([^"]+)"|(?:--config|-f)\s+(\S+)')
_DBPATH_PATTERN = re.compile(r"^\s*dbPath\s*:\s*(.+?)\s*$", re.MULTILINE)
_AUTH_ENABLED_PATTERN = re.compile(r"^\s*authorization\s*:\s*[\"']?enabled[\"']?\s*$", re.MULTILINE)
_READY_MARKER = "waiting for connections"
_ADMIN_USERNAME = "root"
_STARTUP_TIMEOUT = 30
_POLL_INTERVAL = 0.5
_DEFAULT_PORT = 27017


class MongoDBAdapter(DatabaseAdapter):
    dbms = DBMS.MONGODB

    def __init__(
        self,
        service_manager: ServiceManager | None = None,
        detection_engine: DetectionEngine | None = None,
    ) -> None:
        self.service_manager = service_manager or ServiceManager()
        self.detection_engine = detection_engine or DetectionEngine()

    def detect(self) -> DetectionResult:
        return self.detection_engine.detect(DBMS.MONGODB)

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
                "Only the MongoDB client was detected, not a server "
                "installation, so the password can't be changed from here.",
            )
        if not installation.executable_path:
            return OperationResult(
                False, False,
                "No mongod executable path was recorded for this installation.",
            )

        mongod = Path(installation.executable_path)
        dbpath = self._resolve_dbpath(installation)
        if dbpath is None:
            return OperationResult(
                False, False,
                "Couldn't determine MongoDB's data directory, so the password "
                "change was not attempted.",
            )

        mongosh = self._locate_sibling(installation, "mongosh")
        if mongosh is None:
            return OperationResult(
                False, False,
                "Couldn't locate mongosh alongside this MongoDB installation.",
            )

        service_name = installation.service_name
        was_running = False
        if service_name:
            was_running = self.service_manager.get_service_state(service_name) == "RUNNING"
            if was_running:
                logger.info("Stopping MongoDB service before password reset.")
                if not self.service_manager.stop_service(service_name):
                    return OperationResult(
                        False, False,
                        f"Could not stop the {service_name} service, so the "
                        "password was not changed. No changes were made.",
                    )

        reset_succeeded = self._apply_new_password(mongod, mongosh, dbpath, new_password)

        if not reset_succeeded:
            self._restore_service_state(service_name, was_running)
            return OperationResult(
                False, False,
                "MongoDB did not start cleanly, or the user could not be "
                f"updated. This assumes an administrative user named "
                f"'{_ADMIN_USERNAME}' -- if this deployment uses a different "
                "admin username, that is the likely cause. No confirmed "
                "change was made.",
                restored_configuration=None,
            )

        restored = self._restore_service_state(service_name, was_running)
        if restored is False:
            return OperationResult(
                True, False,
                "The password was changed, but the MongoDB service could not "
                f"be restarted automatically. Start {service_name} manually "
                "to finish.",
                restored_configuration=False,
            )

        return OperationResult(
            success=True, verified=False, message="Password changed.",
            restored_configuration=restored,
        )

    def verify(self, installation: Installation, password: str) -> bool:
        register_secret(password)
        mongosh = self._locate_sibling(installation, "mongosh")
        if mongosh is None:
            logger.warning("Could not locate mongosh to verify the new password.")
            return False

        port = self._resolve_port(installation) or _DEFAULT_PORT
        script = self._write_script(
            "const conn = db.getSiblingDB('admin');\n"
            f"const ok = conn.auth({_js_string(_ADMIN_USERNAME)}, {_js_string(password)});\n"
            "if (!ok) { quit(1); }\n"
        )
        try:
            result = process.run(
                [str(mongosh), "--quiet", f"mongodb://127.0.0.1:{port}/admin", "--file", str(script)],
                timeout=10,
            )
        except Exception as exc:
            logger.debug("Verification connection failed: %s", type(exc).__name__)
            return False
        finally:
            self._delete_temp_file(script)

        return result.ok

    # ------------------------------------------------------------------
    # Discovery helpers
    # ------------------------------------------------------------------
    def _resolve_config(self, installation: Installation) -> str | None:
        if not installation.service_name:
            return None
        binary_path = self.service_manager.get_service_binary_path(installation.service_name)
        if not binary_path:
            return None
        match = _CONFIG_ARG_PATTERN.search(binary_path)
        if not match:
            return None
        config_path = match.group(1) or match.group(2)
        try:
            return Path(config_path).read_text(errors="replace")
        except OSError:
            return None

    def _resolve_dbpath(self, installation: Installation) -> Path | None:
        config = self._resolve_config(installation)
        if not config:
            return None
        match = _DBPATH_PATTERN.search(config)
        if not match:
            return None
        candidate = Path(match.group(1).strip())
        return candidate if candidate.exists() else None

    def _resolve_port(self, installation: Installation) -> int | None:
        config = self._resolve_config(installation)
        if not config:
            return None
        match = re.search(r"^\s*port\s*:\s*(\d+)\s*$", config, re.MULTILINE)
        return int(match.group(1)) if match else None

    def _config_requires_auth(self, installation: Installation) -> bool:
        config = self._resolve_config(installation)
        return bool(config and _AUTH_ENABLED_PATTERN.search(config))

    def _locate_sibling(self, installation: Installation, name: str) -> Path | None:
        if installation.executable_path:
            reference = Path(installation.executable_path)
            candidate = reference.with_name(name + reference.suffix)
            if candidate.exists():
                return candidate
        located = which(name)
        return Path(located) if located else None

    # ------------------------------------------------------------------
    # The reset procedure
    # ------------------------------------------------------------------
    def _apply_new_password(
        self, mongod: Path, mongosh: Path, dbpath: Path, new_password: str
    ) -> bool:
        try:
            proc = process.start(
                [
                    str(mongod),
                    f"--dbpath={dbpath}",
                    "--bind_ip", "127.0.0.1",
                    "--port", str(_DEFAULT_PORT),
                    "--noauth",
                ]
            )
        except Exception as exc:
            logger.warning("Could not start mongod: %s", type(exc).__name__)
            return False

        ready = self._wait_for_ready_or_exit(proc, _STARTUP_TIMEOUT)
        if ready:
            escaped = new_password.replace("\\", "\\\\").replace("'", "\\'")
            script = self._write_script(
                "const conn = db.getSiblingDB('admin');\n"
                f"conn.updateUser({_js_string(_ADMIN_USERNAME)}, "
                f"{{pwd: {_js_string(new_password)}}});\n"
            )
            try:
                result = process.run(
                    [str(mongosh), "--quiet", f"mongodb://127.0.0.1:{_DEFAULT_PORT}/admin", "--file", str(script)],
                    timeout=15,
                )
                ready = result.ok
            except Exception as exc:
                logger.warning("mongosh updateUser failed: %s", type(exc).__name__)
                ready = False
            finally:
                self._delete_temp_file(script)

        self._shutdown_reset_process(proc, mongosh)
        return ready

    @staticmethod
    def _wait_for_ready_or_exit(proc: subprocess.Popen, timeout: float) -> bool:
        """Watch mongod's stdout for its startup-complete marker (mongod logs
        to stdout by default when no --logpath is given)."""
        if proc.stdout is None:
            return False

        line_queue: queue.Queue = queue.Queue()

        def _pump() -> None:
            for line in iter(proc.stdout.readline, ""):
                line_queue.put(line)
            line_queue.put(None)

        threading.Thread(target=_pump, daemon=True).start()

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                return False
            try:
                line = line_queue.get(timeout=_POLL_INTERVAL)
            except queue.Empty:
                continue
            if line is None:
                return False
            if _READY_MARKER in line.lower():
                return True
        return False

    def _shutdown_reset_process(self, proc: subprocess.Popen, mongosh: Path) -> None:
        if proc.poll() is not None:
            return

        script = self._write_script(
            "db.getSiblingDB('admin').shutdownServer({force: true});\n"
        )
        try:
            process.run(
                [str(mongosh), "--quiet", f"mongodb://127.0.0.1:{_DEFAULT_PORT}/admin", "--file", str(script)],
                timeout=15,
            )
        except Exception as exc:
            logger.debug("Graceful shutdown via mongosh failed: %s", type(exc).__name__)
        finally:
            self._delete_temp_file(script)

        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    def _restore_service_state(self, service_name: str | None, was_running: bool) -> bool | None:
        if not service_name or not was_running:
            return None
        logger.info("Restarting MongoDB service after password reset.")
        return self.service_manager.start_service(service_name)

    # ------------------------------------------------------------------
    # Temp-file helpers (Rule 4: never persist a password)
    # ------------------------------------------------------------------
    @staticmethod
    def _write_script(content: str) -> Path:
        fd, path_str = tempfile.mkstemp(prefix="setu_mongo_script_", suffix=".js")
        path = Path(path_str)
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(fd, "w") as handle:
                handle.write(content)
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            path.unlink(missing_ok=True)
            raise
        return path

    @staticmethod
    def _delete_temp_file(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not delete temporary file -- remove it manually.")


def _js_string(value: str) -> str:
    """Render a Python string as a single-quoted JavaScript string literal."""
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"
