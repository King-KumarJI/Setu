"""
Regression test for Phase 6's stated exit criterion:
"No secrets appear in logs or persistent files."

Two things are checked end to end, not just reasoned about by reading
the source:

1. A full password-change flow (password_manager.change_password,
   the same entry point the GUI uses) with logging captured -- the
   plaintext password must not appear anywhere in the captured log
   output.

2. Every adapter's secret-bearing temp-file helper (the mechanism
   audited manually in the Phase 6 temp-file-cleanup pass) -- the
   plaintext password must not remain in any file on disk once the
   helper's own cleanup call has run, and no stray "setu_*" temp file
   should be left behind in the OS temp directory at all.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

from app.core.models import DBMS
from app.core.password_manager import PasswordChangeRequest, change_password
from app.databases.mariadb import MariaDBAdapter
from app.databases.mock import MockAdapter
from app.databases.mongodb import MongoDBAdapter
from app.databases.mysql import MySQLAdapter
from app.databases.postgresql import PostgreSQLAdapter
from app.utils.logging import clear_secrets

SECRET = "R3gr3ssion!Secret_9x"


def _leftover_setu_temp_files() -> set[Path]:
    import tempfile

    return set(Path(tempfile.gettempdir()).glob("setu_*"))


def test_full_password_change_flow_never_logs_the_plaintext_secret():
    """Drives the real orchestration path (password_manager.change_password)
    against MockAdapter -- the same call the GUI makes -- with every
    logger it touches captured, and asserts the secret never appears."""
    clear_secrets()

    captured = io.StringIO()
    capture_handler = logging.StreamHandler(captured)
    capture_handler.setLevel(logging.DEBUG)

    logger_names = ["app.core.password_manager", "app.core.verifier"]
    loggers = [logging.getLogger(name) for name in logger_names]
    for logger in loggers:
        logger.addHandler(capture_handler)

    try:
        adapter = MockAdapter(DBMS.POSTGRESQL)
        request = PasswordChangeRequest(
            installation=adapter.get_installations()[0],
            new_password=SECRET,
            confirm_password=SECRET,
        )
        result = change_password(adapter, request)
    finally:
        for logger in loggers:
            logger.removeHandler(capture_handler)
        clear_secrets()

    assert result.success
    output = captured.getvalue()
    assert SECRET not in output


def _assert_file_had_secret_then_is_gone(path, delete_fn):
    """Sanity-checks the helper actually wrote the secret (so this test
    would fail loudly if a future change stopped embedding it), then
    runs the adapter's own cleanup call and confirms the file is gone."""
    assert path.exists()
    assert SECRET in path.read_text()
    delete_fn(path)
    assert not path.exists()


def test_mysql_temp_files_do_not_survive_cleanup():
    before = _leftover_setu_temp_files()

    init_path = MySQLAdapter._write_init_file(SECRET)
    _assert_file_had_secret_then_is_gone(init_path, MySQLAdapter._delete_temp_file)

    defaults_path = MySQLAdapter._write_client_defaults_file(SECRET)
    _assert_file_had_secret_then_is_gone(defaults_path, MySQLAdapter._delete_temp_file)

    assert _leftover_setu_temp_files() == before


def test_mariadb_temp_files_do_not_survive_cleanup():
    before = _leftover_setu_temp_files()

    init_path = MariaDBAdapter._write_init_file(SECRET)
    _assert_file_had_secret_then_is_gone(init_path, MariaDBAdapter._delete_temp_file)

    defaults_path = MariaDBAdapter._write_client_defaults_file(SECRET)
    _assert_file_had_secret_then_is_gone(defaults_path, MariaDBAdapter._delete_temp_file)

    assert _leftover_setu_temp_files() == before


def test_postgresql_pgpass_file_does_not_survive_cleanup():
    before = _leftover_setu_temp_files()

    pgpass_path = PostgreSQLAdapter._write_pgpass_file("127.0.0.1", 5432, SECRET)
    _assert_file_had_secret_then_is_gone(pgpass_path, PostgreSQLAdapter._delete_temp_file)

    assert _leftover_setu_temp_files() == before


def test_mongodb_script_file_does_not_survive_cleanup():
    before = _leftover_setu_temp_files()

    script_path = MongoDBAdapter._write_script(
        f"conn.updateUser('root', {{pwd: '{SECRET}'}});\n"
    )
    _assert_file_had_secret_then_is_gone(script_path, MongoDBAdapter._delete_temp_file)

    assert _leftover_setu_temp_files() == before
