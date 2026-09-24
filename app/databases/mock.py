"""
Mock adapter for exercising the GUI without a real DBMS.

Not part of the production adapter registry -- used by tests (and
available for manual/dev exploration) to satisfy Phase 2's exit
criterion: "The GUI works with mocked adapters without requiring
real password changes."
"""
from __future__ import annotations

from app.core.models import (
    DBMS,
    DetectionResult,
    DetectionStatus,
    Installation,
    OperationResult,
)
from app.databases.base import DatabaseAdapter


class MockAdapter(DatabaseAdapter):
    """Always reports one detected, running installation and a successful,
    verified password change. Never touches a real database or process."""

    def __init__(self, dbms: DBMS) -> None:
        self.dbms = dbms

    def detect(self) -> DetectionResult:
        return DetectionResult(dbms=self.dbms, installations=self.get_installations())

    def get_installations(self) -> list[Installation]:
        return [
            Installation(
                dbms=self.dbms,
                status=DetectionStatus.SERVER_RUNNING,
                version="0.0.0-mock",
                executable_path=f"/mock/{self.dbms.value.lower()}",
                service_name=f"{self.dbms.value}Mock",
            )
        ]

    def get_version(self, installation: Installation) -> str | None:
        return installation.version

    def change_password(
        self, installation: Installation, new_password: str
    ) -> OperationResult:
        return OperationResult(
            success=True,
            verified=False,
            message="Password changed (mock -- no real database was touched).",
            restored_configuration=None,
        )

    def verify(self, installation: Installation, password: str) -> bool:
        return True
