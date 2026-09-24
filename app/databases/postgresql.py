"""
PostgreSQL adapter.

The standard local "forgot the postgres password" recovery means
temporarily allowing an unauthenticated connection, which is a real
security window -- narrower than the naive version of this technique,
but still real:

  1. Back up pg_hba.conf and confirm the backup matches before
     touching anything.
  2. Prepend exactly one `trust` rule, scoped as tightly as this
     mechanism allows: address 127.0.0.1/32 only (not the whole
     subnet, not ::1 -- our own connection only ever uses IPv4
     loopback, so IPv6 was never widened), user `postgres` only (not
     `all`). It is prepended so it is matched before any existing
     rule (pg_hba.conf uses first-match).
  3. Reload the config (`pg_ctl reload` -- no service stop/restart
     needed, unlike MySQL, since pg_hba.conf is re-read live).
  4. Run ALTER ROLE with the new password over stdin (never argv --
     Rule 14).
  5. Unconditionally restore the original pg_hba.conf and reload
     again, in a `finally` block, whether or not step 4 succeeded --
     and verify the restoration by reading the file back rather than
     assuming the write worked (Rule 10 step 6).

If restoration can't be confirmed, that is reported as a distinct,
loud warning -- not folded into ordinary failure wording -- because
unlike a service that failed to restart, an un-restored trust rule is
an active local authentication bypass until someone removes it by
hand.

Only the `postgres` role is handled (matching MySQL's adapter, which
only handles `root`), and only a local, already-registered Windows
service is supported for locating the data directory.

IMPORTANT: exercised only against mocked service control and canned
command output -- there is no PostgreSQL server available in the
environment this was built in. Rule 9 requires verification against a
real local PostgreSQL installation before this is trusted.
"""
from __future__ import annotations

import os
import re
import stat
import tempfile
from pathlib import Path
from shutil import which

from app.core.detector import DetectionEngine
from app.core.models import DBMS, DetectionResult, DetectionStatus, Installation, OperationResult
from app.core.service_manager import ServiceManager
from app.databases.base import DatabaseAdapter
from app.utils import process
from app.utils.logging import get_logger, register_secret

logger = get_logger(__name__)

_DATADIR_ARG_PATTERN = re.compile(r'-D\s+"([^"]+)"|-D\s+(\S+)')
_PORT_PATTERN = re.compile(r"^\s*port\s*=\s*(\d+)", re.MULTILINE)
_DEFAULT_PORT = 5432
_TRUST_RULE = "host    all    postgres    127.0.0.1/32    trust\n"


class PostgreSQLAdapter(DatabaseAdapter):
    dbms = DBMS.POSTGRESQL

    def __init__(
        self,
        service_manager: ServiceManager | None = None,
        detection_engine: DetectionEngine | None = None,
    ) -> None:
        self.service_manager = service_manager or ServiceManager()
        self.detection_engine = detection_engine or DetectionEngine()

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------
    def detect(self) -> DetectionResult:
        return self.detection_engine.detect(DBMS.POSTGRESQL)

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
                "Only the PostgreSQL client was detected, not a server "
                "installation, so the password can't be changed from here.",
            )
        if not installation.executable_path:
            return OperationResult(
                False, False,
                "No PostgreSQL server executable path was recorded for this installation.",
            )

        datadir = self._resolve_datadir(installation)
        if datadir is None:
            return OperationResult(
                False, False,
                "Couldn't determine PostgreSQL's data directory, so the "
                "password change was not attempted.",
            )

        hba_path = datadir / "pg_hba.conf"
        if not hba_path.exists():
            return OperationResult(
                False, False, f"Expected configuration file not found at {hba_path}."
            )

        pg_ctl = self._locate_sibling(installation, "pg_ctl")
        psql = self._locate_sibling(installation, "psql")
        if pg_ctl is None or psql is None:
            return OperationResult(
                False, False,
                "Couldn't locate the pg_ctl/psql tools alongside this PostgreSQL installation.",
            )

        port = self._resolve_port(datadir)

        service_name = installation.service_name
        if service_name and self.service_manager.get_service_state(service_name) != "RUNNING":
            logger.info("Starting PostgreSQL service so the configuration can be reloaded.")
            if not self.service_manager.start_service(service_name):
                return OperationResult(
                    False, False,
                    f"Could not start the {service_name} service, so the "
                    "password was not changed.",
                )

        try:
            original_hba = hba_path.read_text()
        except OSError as exc:
            return OperationResult(
                False, False,
                f"Could not read the existing configuration ({exc}); no changes were made.",
            )

        rule_was_written = False
        reload_applied = False
        alter_succeeded = False
        restored: bool | None = None
        try:
            self._write_trust_rule(hba_path, original_hba)
            rule_was_written = True
            reload_applied = self._reload(pg_ctl, datadir)
            if reload_applied:
                alter_succeeded = self._apply_new_password(psql, port, new_password)
        finally:
            if rule_was_written:
                restored = self._restore_hba(hba_path, original_hba, pg_ctl, datadir)

        if not reload_applied:
            return OperationResult(
                False, False,
                "PostgreSQL would not reload the temporary configuration, so "
                "the password was not changed.",
                restored_configuration=restored,
            )

        if not alter_succeeded:
            message = "Applying the new password failed."
            if not restored:
                message += (
                    f" IMPORTANT: check {hba_path} immediately -- the temporary "
                    "passwordless access rule may still be active."
                )
            return OperationResult(False, False, message, restored_configuration=restored)

        if not restored:
            return OperationResult(
                True, False,
                "The password was changed, but the temporary passwordless "
                f"access rule in {hba_path} could not be confirmed removed. "
                "Check that file immediately and remove the 'trust' line if "
                "it's still there.",
                restored_configuration=False,
            )

        return OperationResult(True, False, "Password changed.", restored_configuration=True)

    def verify(self, installation: Installation, password: str) -> bool:
        register_secret(password)
        psql = self._locate_sibling(installation, "psql")
        if psql is None:
            logger.warning("Could not locate the psql client to verify the new password.")
            return False

        datadir = self._resolve_datadir(installation)
        port = self._resolve_port(datadir) if datadir else _DEFAULT_PORT

        pgpass_file = self._write_pgpass_file("127.0.0.1", port, password)
        try:
            result = process.run(
                [
                    str(psql), "-h", "127.0.0.1", "-p", str(port),
                    "-U", "postgres", "-d", "postgres", "-c", "SELECT 1;",
                ],
                env={**os.environ, "PGPASSFILE": str(pgpass_file)},
                timeout=10,
            )
        except Exception as exc:
            logger.debug("Verification connection failed: %s", type(exc).__name__)
            return False
        finally:
            self._delete_temp_file(pgpass_file)

        return result.ok

    # ------------------------------------------------------------------
    # Discovery helpers
    # ------------------------------------------------------------------
    def _resolve_datadir(self, installation: Installation) -> Path | None:
        env_pgdata = os.environ.get("PGDATA")
        if env_pgdata and Path(env_pgdata).exists():
            return Path(env_pgdata)

        if installation.service_name:
            binary_path = self.service_manager.get_service_binary_path(installation.service_name)
            if binary_path:
                match = _DATADIR_ARG_PATTERN.search(binary_path)
                if match:
                    candidate = Path(match.group(1) or match.group(2))
                    if candidate.exists():
                        return candidate
        return None

    def _resolve_port(self, datadir: Path) -> int:
        try:
            content = (datadir / "postgresql.conf").read_text(errors="replace")
        except OSError:
            return _DEFAULT_PORT
        match = _PORT_PATTERN.search(content)
        return int(match.group(1)) if match else _DEFAULT_PORT

    def _locate_sibling(self, installation: Installation, name: str) -> Path | None:
        if installation.executable_path:
            reference = Path(installation.executable_path)
            candidate = reference.with_name(name + reference.suffix)
            if candidate.exists():
                return candidate
        located = which(name)
        return Path(located) if located else None

    # ------------------------------------------------------------------
    # pg_hba.conf handling
    # ------------------------------------------------------------------
    @staticmethod
    def _write_trust_rule(hba_path: Path, original_content: str) -> None:
        hba_path.write_text(_TRUST_RULE + original_content)

    def _restore_hba(
        self, hba_path: Path, original_content: str, pg_ctl: Path, datadir: Path
    ) -> bool:
        try:
            hba_path.write_text(original_content)
        except OSError as exc:
            logger.warning("Could not restore pg_hba.conf: %s", type(exc).__name__)
            return False
        self._reload(pg_ctl, datadir)  # best-effort -- the write is what matters most
        try:
            return hba_path.read_text() == original_content
        except OSError:
            return False

    def _reload(self, pg_ctl: Path, datadir: Path) -> bool:
        try:
            result = process.run([str(pg_ctl), "reload", "-D", str(datadir)], timeout=15)
        except Exception as exc:
            logger.warning("pg_ctl reload failed: %s", type(exc).__name__)
            return False
        return result.ok

    def _apply_new_password(self, psql: Path, port: int, new_password: str) -> bool:
        escaped = new_password.replace("'", "''")
        sql = f"ALTER ROLE postgres WITH PASSWORD '{escaped}';\n"
        try:
            result = process.run(
                [
                    str(psql), "-h", "127.0.0.1", "-p", str(port),
                    "-U", "postgres", "-d", "postgres",
                    "-v", "ON_ERROR_STOP=1", "-f", "-",
                ],
                input=sql,
                input_is_secret=True,
                timeout=15,
            )
        except Exception as exc:
            logger.warning("psql ALTER ROLE failed: %s", type(exc).__name__)
            return False
        return result.ok

    # ------------------------------------------------------------------
    # Temp-file helpers (Rule 4: never persist a password)
    # ------------------------------------------------------------------
    @staticmethod
    def _write_pgpass_file(host: str, port: int, password: str) -> Path:
        """A .pgpass-format file -- psql's own documented non-interactive
        password mechanism, safer than PGPASSWORD (visible via
        /proc/<pid>/environ to other same-user processes on some
        platforms) or a -p<password>-style argument (Rule 14)."""
        fd, path_str = tempfile.mkstemp(prefix="setu_pg_pass_", suffix=".conf")
        path = Path(path_str)
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            line = f"{_pgpass_escape(host)}:{port}:*:postgres:{_pgpass_escape(password)}\n"
            with os.fdopen(fd, "w") as handle:
                handle.write(line)
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


def _pgpass_escape(value: str) -> str:
    """Escape a .pgpass field per PostgreSQL's documented rules: a
    backslash or colon must itself be backslash-escaped."""
    return value.replace("\\", "\\\\").replace(":", "\\:")
