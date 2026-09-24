"""
Per-DBMS detection signatures.

Pure data: the candidate executable names, Windows service name
patterns, Program Files folder hint, and version-flag arguments used
to discover each DBMS. Kept separate from DetectionEngine so adding
or adjusting a signature never requires touching detection logic
(Rule 24 -- new DBMS support should require adding, not rewriting).

Every field here is a *candidate*, never proof on its own (Rule 5) --
DetectionEngine treats each as one signal among several.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.models import DBMS


@dataclass(frozen=True)
class DBMSSignature:
    dbms: DBMS
    client_executables: tuple[str, ...]
    server_executables: tuple[str, ...]
    service_name_patterns: tuple[str, ...]
    program_files_hint: str
    version_args: tuple[str, ...] = ("--version",)


SIGNATURES: dict[DBMS, DBMSSignature] = {
    DBMS.MYSQL: DBMSSignature(
        dbms=DBMS.MYSQL,
        client_executables=("mysql",),
        server_executables=("mysqld",),
        service_name_patterns=("mysql",),
        program_files_hint="mysql",
    ),
    DBMS.POSTGRESQL: DBMSSignature(
        dbms=DBMS.POSTGRESQL,
        client_executables=("psql",),
        server_executables=("postgres",),
        service_name_patterns=("postgresql",),
        program_files_hint="postgres",
    ),
    DBMS.MARIADB: DBMSSignature(
        dbms=DBMS.MARIADB,
        client_executables=("mariadb",),
        server_executables=("mariadbd",),
        service_name_patterns=("mariadb",),
        program_files_hint="mariadb",
    ),
    DBMS.MONGODB: DBMSSignature(
        dbms=DBMS.MONGODB,
        client_executables=("mongosh",),
        server_executables=("mongod",),
        service_name_patterns=("mongodb", "mongo"),
        program_files_hint="mongo",
    ),
    DBMS.REDIS: DBMSSignature(
        dbms=DBMS.REDIS,
        client_executables=("redis-cli",),
        server_executables=("redis-server",),
        # Redis has no official Windows build; Windows installs are
        # typically Memurai or a community port, so there is no
        # standardized service name -- this pattern is best-effort
        # and documented as a known limitation (see README/Phase 5).
        service_name_patterns=("redis", "memurai"),
        program_files_hint="redis",
    ),
}
