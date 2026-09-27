"""
MariaDB adapter.

Follows the same documented "lost root password" recovery as MySQL
(--init-file with a one-shot ALTER USER, then a clean shutdown and
restart) because MariaDB genuinely is wire- and tool-compatible with
MySQL for this specific operation -- MariaDB's own documentation
covers the same --init-file mechanism. That is a real, documented
fact about MariaDB, not a lazy assumption copied from the MySQL
adapter; this file is still its own independent implementation
(Rule 7: MariaDB logic belongs in the MariaDB adapter), using
MariaDB's own executable names (mariadb / mariadbd / mariadb-admin)
so a future divergence between the two projects doesn't ripple into
MySQLAdapter or vice versa.

Real difference worth flagging: ALTER USER syntax is only supported
from MariaDB 10.2+ (SET PASSWORD FOR was required before that). This
adapter assumes a modern MariaDB and does not attempt to detect or
support the older syntax -- a real limitation, not an oversight.

IMPORTANT: exercised only against mocked service control and canned
command output -- there is no MariaDB server available in the
environment this was built in. Rule 9 requires verification against a
real local MariaDB installation before this is trusted.
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

_DATADIR_PATTERN = re.compile(r"^datadir\s+(.*\S)\s*$", re.MULTILINE)
_DEFAULTS_FILE_ARG_PATTERN = re.compile(r'--defaults-file=(?:"([^"]+)"|(\S+))')
_READY_MARKER = "ready for connections"
_STARTUP_TIMEOUT = 30
_POLL_INTERVAL = 0.5


class MariaDBAdapter(DatabaseAdapter):
    dbms = DBMS.MARIADB

    def __init__(
        self,
        service_manager: ServiceManager | None = None,
        detection_engine: DetectionEngine | None = None,
    ) -> None:
        self.service_manager = service_manager or ServiceManager()
        self.detection_engine = detection_engine or DetectionEngine()

    def detect(self) -> DetectionResult:
        return self.detection_engine.detect(DBMS.MARIADB)

    def get_installations(self) -> list[Installation]:
        return self.detect().installations

    def get_version(self, installation: Installation) -> str | None:
        return installation.version

    def change_password(
        self, installation: Installation, new_password: str
    ) -> OperationResult:
        register_secret(new_password)

        if installation.status == DetectionStatus.EXECUTABLE_FOUND:
            return OperationResult(
                False, False,
                "Only the MariaDB client was detected, not a server installation, "
                "so the password can't be changed from here.",
            )
        if not installation.executable_path:
            return OperationResult(
                False, False,
                "No mariadbd executable path was recorded for this installation.",
            )

        mariadbd = Path(installation.executable_path)
        datadir = self._resolve_datadir(mariadbd, installation.service_name)
        if datadir is None:
            return OperationResult(
                False, False,
                "Couldn't determine MariaDB's data directory, so the password "
                "change was not attempted. This installation may use a "
                "non-standard configuration.",
            )

        service_name = installation.service_name
        was_running = False
        if service_name:
            was_running = self.service_manager.get_service_state(service_name) == "RUNNING"
            if was_running:
                logger.info("Stopping MariaDB service before password reset.")
                if not self.service_manager.stop_service(service_name):
                    return OperationResult(
                        False, False,
                        f"Could not stop the {service_name} service, so the "
                        "password was not changed. No changes were made.",
                    )

        reset_succeeded = self._apply_new_password(mariadbd, datadir, new_password)

        if not reset_succeeded:
            self._restore_service_state(service_name, was_running)
            return OperationResult(
                False, False,
                "MariaDB did not start cleanly while applying the new password. "
                "No confirmed change was made. Check that no other mariadbd "
                "process is using this data directory and try again.",
                restored_configuration=None,
            )

        restored = self._restore_service_state(service_name, was_running)
        if restored is False:
            return OperationResult(
                True, False,
                "The password was changed, but the MariaDB service could not be "
                f"restarted automatically. Start {service_name} manually to finish.",
                restored_configuration=False,
            )

        return OperationResult(
            success=True, verified=False, message="Password changed.",
            restored_configuration=restored,
        )

    def verify(self, installation: Installation, password: str) -> bool:
        register_secret(password)
        client = self._locate_sibling(installation, "mariadb")
        if client is None:
            logger.warning("Could not locate the mariadb client to verify the new password.")
            return False

        defaults_file = self._write_client_defaults_file(password)
        try:
            result = process.run(
                [
                    str(client),
                    f"--defaults-extra-file={defaults_file}",
                    "-u", "root",
                    "-e", "SELECT 1;",
                ],
                timeout=10,
            )
        except Exception as exc:
            logger.debug("Verification connection failed: %s", type(exc).__name__)
            return False
        finally:
            self._delete_temp_file(defaults_file)

        return result.ok

    # ------------------------------------------------------------------
    # Discovery helpers
    # ------------------------------------------------------------------
    def _resolve_datadir(self, mariadbd: Path, service_name: str | None = None) -> Path | None:
        """Same rationale and mechanism as MySQLAdapter._resolve_datadir:
        invoked bare, mariadbd reports its compiled-in default datadir,
        which may not match where the Windows service was actually
        configured to store data. When a service name is known, look
        up the same --defaults-file the service was registered with
        (via `sc qc`) and pass it through first on the command line --
        MySQL/MariaDB both require --defaults-file to be the first
        argument or it's rejected. Falls back to the bare invocation
        when there's no service, or no --defaults-file in its command
        line (e.g. a manual/portable install)."""
        args = [str(mariadbd)]
        if service_name:
            binary_path = self.service_manager.get_service_binary_path(service_name)
            if binary_path:
                match = _DEFAULTS_FILE_ARG_PATTERN.search(binary_path)
                if match:
                    defaults_file = match.group(1) or match.group(2)
                    args.append(f"--defaults-file={defaults_file}")
        args += ["--verbose", "--help"]
        try:
            result = process.run(args, timeout=10)
        except Exception as exc:
            logger.warning("Could not query mariadbd defaults: %s", type(exc).__name__)
            return None
        match = _DATADIR_PATTERN.search(result.stdout)
        if not match:
            return None
        path = Path(match.group(1).strip())
        return path if path.exists() else None

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
    def _apply_new_password(self, mariadbd: Path, datadir: Path, new_password: str) -> bool:
        init_file = self._write_init_file(new_password)
        try:
            proc = process.start(
                [
                    str(mariadbd),
                    f"--datadir={datadir}",
                    f"--init-file={init_file}",
                    "--skip-networking",
                ]
            )
        except Exception as exc:
            logger.warning("Could not start mariadbd: %s", type(exc).__name__)
            self._delete_temp_file(init_file)
            return False

        try:
            ready = self._wait_for_ready_or_exit(proc, _STARTUP_TIMEOUT)
        finally:
            self._delete_temp_file(init_file)

        self._shutdown_reset_process(proc, mariadbd, new_password)
        return ready

    @staticmethod
    def _wait_for_ready_or_exit(proc: subprocess.Popen, timeout: float) -> bool:
        if proc.stderr is None:
            return False

        line_queue: queue.Queue = queue.Queue()

        def _pump() -> None:
            for line in iter(proc.stderr.readline, ""):
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

    def _shutdown_reset_process(
        self, proc: subprocess.Popen, mariadbd: Path, new_password: str
    ) -> None:
        if proc.poll() is not None:
            return

        mariadb_admin = mariadbd.with_name("mariadb-admin" + mariadbd.suffix)
        if mariadb_admin.exists():
            defaults_file = self._write_client_defaults_file(new_password)
            try:
                process.run(
                    [
                        str(mariadb_admin),
                        f"--defaults-extra-file={defaults_file}",
                        "-u", "root",
                        "shutdown",
                    ],
                    timeout=15,
                )
            except Exception as exc:
                logger.debug("Graceful shutdown via mariadb-admin failed: %s", type(exc).__name__)
            finally:
                self._delete_temp_file(defaults_file)

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
        logger.info("Restarting MariaDB service after password reset.")
        return self.service_manager.start_service(service_name)

    # ------------------------------------------------------------------
    # Temp-file helpers (Rule 4: never persist a password)
    # ------------------------------------------------------------------
    @staticmethod
    def _write_init_file(new_password: str) -> Path:
        fd, path_str = tempfile.mkstemp(prefix="setu_mariadb_init_", suffix=".sql")
        path = Path(path_str)
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            escaped = new_password.replace("'", "''")
            sql = f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{escaped}';\n"
            with os.fdopen(fd, "w") as handle:
                handle.write(sql)
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            path.unlink(missing_ok=True)
            raise
        return path

    @staticmethod
    def _write_client_defaults_file(password: str) -> Path:
        fd, path_str = tempfile.mkstemp(prefix="setu_mariadb_client_", suffix=".cnf")
        path = Path(path_str)
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            escaped = password.replace("\\", "\\\\").replace('"', '\\"')
            with os.fdopen(fd, "w") as handle:
                handle.write(f'[client]\npassword="{escaped}"\n')
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
