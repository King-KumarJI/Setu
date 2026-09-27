"""
MySQL adapter.

Implements MySQL's own documented "lost root password" recovery
procedure (MySQL Reference Manual, "Resetting the Root Password: 
Generic Instructions"): stop the server, start mysqld standalone with
a one-shot --init-file containing an ALTER USER statement, confirm it
came up cleanly, shut it down again, and restore the service to
whatever state it was in before. This is the *documented* mechanism,
not a hand-rolled workaround -- Rule 9.

Deliberately the only workflow implemented (matching 05-prd.md's
stated problem: a forgotten local password), not also branching on
whether some other credential already works -- a reasonable future
enhancement, not required for the MVP.

IMPORTANT: this has been exercised only against mocked service
control and canned command output -- there is no MySQL server
available in the environment this was built in to test against for
real. Rule 9 requires verification against a real local MySQL
installation before this is trusted; treat it as implemented-but-
unverified until that happens.
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


class MySQLAdapter(DatabaseAdapter):
    dbms = DBMS.MYSQL

    def __init__(
        self,
        service_manager: ServiceManager | None = None,
        detection_engine: DetectionEngine | None = None,
    ) -> None:
        self.service_manager = service_manager or ServiceManager()
        self.detection_engine = detection_engine or DetectionEngine()

    # ------------------------------------------------------------------
    # Detection (delegates to the shared engine -- Rule 7/8: no
    # DBMS-specific detection logic duplicated per adapter)
    # ------------------------------------------------------------------
    def detect(self) -> DetectionResult:
        return self.detection_engine.detect(DBMS.MYSQL)

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
                "Only the MySQL client was detected, not a server installation, "
                "so the password can't be changed from here.",
            )
        if not installation.executable_path:
            return OperationResult(
                False, False,
                "No mysqld executable path was recorded for this installation.",
            )

        mysqld = Path(installation.executable_path)
        datadir = self._resolve_datadir(mysqld, installation.service_name)
        if datadir is None:
            return OperationResult(
                False, False,
                "Couldn't determine MySQL's data directory, so the password "
                "change was not attempted. This installation may use a "
                "non-standard configuration.",
            )

        service_name = installation.service_name
        was_running = False
        if service_name:
            was_running = self.service_manager.get_service_state(service_name) == "RUNNING"
            if was_running:
                logger.info("Stopping MySQL service before password reset.")
                if not self.service_manager.stop_service(service_name):
                    return OperationResult(
                        False, False,
                        f"Could not stop the {service_name} service, so the "
                        "password was not changed. No changes were made.",
                    )

        reset_succeeded = self._apply_new_password(mysqld, datadir, new_password)

        if not reset_succeeded:
            self._restore_service_state(service_name, was_running)
            return OperationResult(
                False, False,
                "MySQL did not start cleanly while applying the new password. "
                "No confirmed change was made. Check that no other mysqld "
                "process is using this data directory and try again.",
                restored_configuration=None,
            )

        restored = self._restore_service_state(service_name, was_running)
        if restored is False:
            return OperationResult(
                True, False,
                "The password was changed, but the MySQL service could not be "
                f"restarted automatically. Start {service_name} manually to finish.",
                restored_configuration=False,
            )

        return OperationResult(
            success=True,
            verified=False,
            message="Password changed.",
            restored_configuration=restored,
        )

    def verify(self, installation: Installation, password: str) -> bool:
        register_secret(password)
        client = self._locate_sibling(installation, "mysql")
        if client is None:
            logger.warning("Could not locate the mysql client to verify the new password.")
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
    def _resolve_datadir(self, mysqld: Path, service_name: str | None = None) -> Path | None:
        """Ask mysqld for its default datadir via --verbose --help -- a
        documented, standard mysqld behavior (Rule 6/9) -- rather than
        guessing a path.

        Invoked bare, mysqld reports its *compiled-in* default datadir,
        which is very often not where the server actually stores its
        data: MySQL's official Windows installer registers the service
        with an explicit --defaults-file pointing at a my.ini under
        ProgramData, and that file (not the compiled default under
        Program Files) is what sets the real datadir. Verified against
        a real MySQL 8.0 Windows install (Rule 9) -- the compiled
        default reported without --defaults-file does not exist on
        disk there at all. So when a service name is known, look up
        the same --defaults-file the Windows service itself was
        registered with (mirroring how PostgreSQLAdapter recovers its
        datadir from the service's own -D argument) and pass it
        through as --defaults-file -- placed first in the argument
        list, since MySQL requires --defaults-file to be the first
        option on the command line or it's rejected outright. Falls
        back to the bare (compiled-default) invocation when there's no
        service name, no registered service, or no --defaults-file in
        its command line -- e.g. a manual/portable install."""
        args = [str(mysqld)]
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
            logger.warning("Could not query mysqld defaults: %s", type(exc).__name__)
            return None
        match = _DATADIR_PATTERN.search(result.stdout)
        if not match:
            return None
        path = Path(match.group(1).strip())
        return path if path.exists() else None

    def _locate_sibling(self, installation: Installation, name: str) -> Path | None:
        """Look for another MySQL tool next to the known executable first
        (Rule 6: MySQL's bin directory is often not on PATH even when the
        service is registered), falling back to PATH."""
        if installation.executable_path:
            reference = Path(installation.executable_path)
            candidate = reference.with_name(name + reference.suffix)
            if candidate.exists():
                return candidate
        located = which(name)
        return Path(located) if located else None

    # ------------------------------------------------------------------
    # The reset procedure itself
    # ------------------------------------------------------------------
    def _apply_new_password(self, mysqld: Path, datadir: Path, new_password: str) -> bool:
        init_file = self._write_init_file(new_password)
        try:
            proc = process.start(
                [
                    str(mysqld),
                    f"--datadir={datadir}",
                    f"--init-file={init_file}",
                    "--skip-networking",
                ]
            )
        except Exception as exc:
            logger.warning("Could not start mysqld: %s", type(exc).__name__)
            self._delete_temp_file(init_file)
            return False

        try:
            ready = self._wait_for_ready_or_exit(proc, _STARTUP_TIMEOUT)
        finally:
            # The init-file is only needed for the moment mysqld reads it
            # at startup -- delete it immediately either way (Rule 4).
            self._delete_temp_file(init_file)

        self._shutdown_reset_process(proc, mysqld, new_password)
        return ready

    @staticmethod
    def _wait_for_ready_or_exit(proc: subprocess.Popen, timeout: float) -> bool:
        """Watch mysqld's stderr for its startup-complete marker.

        Uses a background reader thread (rather than select()) because
        select() does not work on pipe file descriptors on Windows --
        the actual target platform -- only on sockets there.
        """
        if proc.stderr is None:
            return False

        line_queue: queue.Queue = queue.Queue()

        def _pump() -> None:
            for line in iter(proc.stderr.readline, ""):
                line_queue.put(line)
            line_queue.put(None)

        reader = threading.Thread(target=_pump, daemon=True)
        reader.start()

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
        self, proc: subprocess.Popen, mysqld: Path, new_password: str
    ) -> None:
        """Shut the standalone reset instance down cleanly via mysqladmin,
        authenticated with the password we just set -- the documented
        clean-shutdown path, since Popen.terminate() is not a graceful
        stop on Windows."""
        if proc.poll() is not None:
            return

        mysqladmin = mysqld.with_name("mysqladmin" + mysqld.suffix)
        if mysqladmin.exists():
            defaults_file = self._write_client_defaults_file(new_password)
            try:
                process.run(
                    [
                        str(mysqladmin),
                        f"--defaults-extra-file={defaults_file}",
                        "-u", "root",
                        "shutdown",
                    ],
                    timeout=15,
                )
            except Exception as exc:
                logger.debug("Graceful shutdown via mysqladmin failed: %s", type(exc).__name__)
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
        """Put the Windows service back the way we found it.

        Returns None when nothing needed restoring (no service, or it
        was already stopped -- we never touched its running state).
        """
        if not service_name or not was_running:
            return None
        logger.info("Restarting MySQL service after password reset.")
        return self.service_manager.start_service(service_name)

    # ------------------------------------------------------------------
    # Temp-file helpers (Rule 4: a password must never be persisted --
    # these files exist only for the instant a tool needs to read them)
    # ------------------------------------------------------------------
    @staticmethod
    def _write_init_file(new_password: str) -> Path:
        """A one-shot SQL file for mysqld --init-file -- MySQL's own
        documented password-reset mechanism, not a hand-rolled hack."""
        fd, path_str = tempfile.mkstemp(prefix="setu_mysql_init_", suffix=".sql")
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
        """A `--defaults-extra-file` for the mysql/mysqladmin client -- the
        documented safer alternative to a `-p<password>` argument, which
        would be visible to any other process inspecting argv (Rule 14)."""
        fd, path_str = tempfile.mkstemp(prefix="setu_mysql_client_", suffix=".cnf")
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
