"""
Abstract interface every database adapter must implement.

Rule 7 (adapters own DB-specific logic) / Rule 8 (no giant
conditional): the GUI and core orchestration code depend only on
this interface, never on a specific DBMS. Adding a new DBMS means
adding a new subclass here, not touching the GUI or core modules.
"""
from __future__ import annotations

import abc

from app.core.models import DBMS, DetectionResult, Installation, OperationResult


class DatabaseAdapter(abc.ABC):
    """Base class for one DBMS's detection and password-change logic."""

    dbms: DBMS

    @abc.abstractmethod
    def detect(self) -> DetectionResult:
        """Discover whether this DBMS is present and its server state.

        Must distinguish executable-found from server-found from
        running from accessible (Rule 5) -- never collapse these.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def get_installations(self) -> list[Installation]:
        """Return every installation found.

        Must not silently pick one when more than one exists (FR-04) --
        that choice belongs to the user via the GUI.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def get_version(self, installation: Installation) -> str | None:
        """Return version info for one installation, if determinable safely."""
        raise NotImplementedError

    @abc.abstractmethod
    def change_password(
        self, installation: Installation, new_password: str
    ) -> OperationResult:
        """Change the administrator password for one installation.

        Implementations must never attempt to discover the *previous*
        password (Rule 2); must back up, validate, and restore any
        configuration they touch (Rule 10); must never persist or log
        the new password (Rule 3 / Rule 4) -- register it with
        `app.utils.logging.register_secret` rather than ever writing
        it to a log line, file, or exception message; and must not
        pass it as a command-line argument when a safer channel is
        available (Rule 14).
        """
        raise NotImplementedError

    @abc.abstractmethod
    def verify(self, installation: Installation, password: str) -> bool:
        """Confirm the given password actually authenticates (Rule 17)."""
        raise NotImplementedError
