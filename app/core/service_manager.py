"""
Windows service discovery and control.

Isolated from the database adapters so future Linux/macOS support
does not require rewriting adapter logic (Rule 19). Discovery
(list_services/find_services) degrades gracefully to an empty result
on a non-Windows machine -- an absence of proof, not proof of
absence (Rule 5). Control (stop_service/start_service) is different:
silently no-op-ing a requested state change would be dangerous, so
those raise clearly instead of pretending to succeed (Rule 25: when
uncertain, stop).
"""
from __future__ import annotations

import platform
import re
import time
from dataclasses import dataclass

from app.utils import process
from app.utils.logging import get_logger

logger = get_logger(__name__)

_POLL_INTERVAL = 0.5


@dataclass(frozen=True)
class ServiceInfo:
    name: str
    display_name: str
    state: str  # raw sc.exe state word, e.g. "RUNNING", "STOPPED"


class NotWindowsError(RuntimeError):
    """Raised by a control operation (start/stop) on a non-Windows machine."""


class ServiceManager:
    """Queries and controls Windows services via `sc` (Rule 9: a documented, standard command)."""

    def is_supported(self) -> bool:
        return platform.system() == "Windows"

    def list_services(self) -> list[ServiceInfo]:
        """Return every Windows service, or [] on a non-Windows machine or on failure.

        An empty result here is a platform/query limitation, not proof
        of anything -- callers must not treat it alone as "not
        detected" (Rule 5); it is only one signal among several.
        """
        if not self.is_supported():
            return []
        try:
            result = process.run(
                ["sc", "query", "type=", "service", "state=", "all"], timeout=15
            )
        except Exception as exc:  # sc.exe missing, timeout, etc. -- degrade gracefully
            logger.warning("Service query failed: %s", type(exc).__name__)
            return []
        if not result.ok:
            logger.warning("`sc query` exited with code %s", result.returncode)
            return []
        return self._parse_sc_query_output(result.stdout)

    def find_services(self, name_patterns: tuple[str, ...]) -> list[ServiceInfo]:
        """Return services whose name or display name contains any of the given
        (case-insensitive) substrings.

        Substring matching, not an exact name, because DBMS installers
        vary service names by version/vendor (e.g. "MySQL80",
        "postgresql-x64-16") -- Rule 6 applies to service names just
        as much as to file paths.
        """
        patterns = [p.lower() for p in name_patterns]
        matches = []
        for service in self.list_services():
            haystack = f"{service.name} {service.display_name}".lower()
            if any(pattern in haystack for pattern in patterns):
                matches.append(service)
        return matches

    def get_service_state(self, service_name: str) -> str | None:
        """Return one service's current state word, or None if it can't be found."""
        if not self.is_supported():
            return None
        try:
            result = process.run(["sc", "query", service_name], timeout=10)
        except Exception as exc:
            logger.warning("Service state query failed: %s", type(exc).__name__)
            return None
        if not result.ok:
            return None
        services = self._parse_sc_query_output(result.stdout)
        return services[0].state if services else None

    def stop_service(self, service_name: str, timeout: float = 30) -> bool:
        """Stop a service and wait for it to actually reach STOPPED.

        Returns False (never raises) on an ordinary failure to stop --
        callers are expected to treat that as "no changes were made"
        and abort, not to guess at the cause. Raises NotWindowsError
        on a non-Windows machine, since silently doing nothing here
        would be misleading about a state-changing request.
        """
        if not self.is_supported():
            raise NotWindowsError("Service control is only supported on Windows.")
        try:
            process.run(["sc", "stop", service_name], timeout=15)
        except Exception as exc:
            logger.warning("`sc stop %s` failed: %s", service_name, type(exc).__name__)
            return False
        return self._wait_for_state(service_name, "STOPPED", timeout)

    def start_service(self, service_name: str, timeout: float = 30) -> bool:
        """Start a service and wait for it to actually reach RUNNING.

        Same failure contract as stop_service().
        """
        if not self.is_supported():
            raise NotWindowsError("Service control is only supported on Windows.")
        try:
            process.run(["sc", "start", service_name], timeout=15)
        except Exception as exc:
            logger.warning("`sc start %s` failed: %s", service_name, type(exc).__name__)
            return False
        return self._wait_for_state(service_name, "RUNNING", timeout)

    def get_service_binary_path(self, service_name: str) -> str | None:
        """Return the raw BINARY_PATH_NAME a service was registered with.

        PostgreSQL's Windows installer registers its service with an
        explicit `-D <datadir>` argument in this command line -- this
        is how the adapter recovers the data directory without needing
        working credentials first (Rule 9: `sc qc` is a documented,
        standard command; the exact command-line shape still needs
        verification against a real installed service).
        """
        if not self.is_supported():
            return None
        try:
            result = process.run(["sc", "qc", service_name], timeout=10)
        except Exception as exc:
            logger.warning("Service config query failed: %s", type(exc).__name__)
            return None
        if not result.ok:
            return None
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("BINARY_PATH_NAME"):
                return stripped.split(":", 1)[1].strip()
        return None

    def _wait_for_state(self, service_name: str, target_state: str, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.get_service_state(service_name) == target_state:
                return True
            time.sleep(_POLL_INTERVAL)
        return self.get_service_state(service_name) == target_state

    @staticmethod
    def _parse_sc_query_output(text: str) -> list[ServiceInfo]:
        """Parse `sc query` output into ServiceInfo records.

        A pure function (no I/O) so it can be unit tested against
        canned output without an actual Windows machine.
        """
        services: list[ServiceInfo] = []
        name: str | None = None
        display_name: str | None = None
        state: str | None = None

        def flush() -> None:
            if name is not None:
                services.append(
                    ServiceInfo(
                        name=name,
                        display_name=display_name or name,
                        state=state or "UNKNOWN",
                    )
                )

        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("SERVICE_NAME:"):
                flush()
                name = stripped.split(":", 1)[1].strip()
                display_name = None
                state = None
            elif stripped.startswith("DISPLAY_NAME:"):
                display_name = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("STATE"):
                # e.g. "STATE              : 4  RUNNING"
                match = re.search(r":\s*\d+\s+(\w+)", stripped)
                if match:
                    state = match.group(1)
        flush()
        return services
