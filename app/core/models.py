"""
Core data models shared across detection, adapters, and the GUI.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field


class DBMS(enum.Enum):
    """Supported (or scaffolded) database systems."""

    MYSQL = "MySQL"
    POSTGRESQL = "PostgreSQL"
    MONGODB = "MongoDB"
    MARIADB = "MariaDB"
    REDIS = "Redis"

    def __str__(self) -> str:  # nicer for GUI dropdown labels
        return self.value


class DetectionStatus(enum.Enum):
    """How confirmed a detection result is, least to most certain.

    Detection code must never collapse these into a single
    found/not-found boolean -- Rule 5 (do not trust PATH alone)
    depends on keeping them distinct: finding a client executable
    must not automatically mean a server is running.
    """

    NOT_DETECTED = "not_detected"
    EXECUTABLE_FOUND = "executable_found"
    INSTALLATION_IDENTIFIED = "installation_identified"
    SERVER_FOUND = "server_found"
    SERVER_RUNNING = "server_running"
    SERVER_ACCESSIBLE = "server_accessible"


_STATUS_ORDER = list(DetectionStatus)


@dataclass(frozen=True)
class Installation:
    """One discovered installation of a DBMS on this machine."""

    dbms: DBMS
    status: DetectionStatus
    version: str | None = None
    executable_path: str | None = None
    service_name: str | None = None
    notes: str = ""


@dataclass(frozen=True)
class DetectionResult:
    """The full detection outcome for one DBMS across the machine."""

    dbms: DBMS
    installations: list[Installation] = field(default_factory=list)

    @property
    def status(self) -> DetectionStatus:
        """The most-confirmed status across all installations found."""
        if not self.installations:
            return DetectionStatus.NOT_DETECTED
        return max(
            (inst.status for inst in self.installations),
            key=_STATUS_ORDER.index,
        )

    @property
    def has_multiple_installations(self) -> bool:
        return len(self.installations) > 1


@dataclass(frozen=True)
class OperationResult:
    """Outcome of a password-change (or other) adapter operation.

    `verified` is deliberately separate from `success`: an adapter can
    report the change as having succeeded server-side while
    verification could not confirm it (e.g. a transient connection
    issue). The GUI must show that as its own state, never collapse
    it into a plain failure (Rule 17) or a plain success.
    """

    success: bool
    verified: bool
    message: str
    restored_configuration: bool | None = None  # None when no config was touched
