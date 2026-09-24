"""
Detection engine.

Combines PATH-based executable discovery, a secondary Program Files
scan, and Windows service discovery into a single DetectionResult per
DBMS (01-architecture.md section 4). Never collapses "executable
found" into "server running" -- Rule 5: finding a client executable
must not automatically mean a database server is running.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
from pathlib import Path

from app.core.models import DBMS, DetectionResult, DetectionStatus, Installation
from app.core.service_manager import ServiceManager
from app.core.signatures import SIGNATURES, DBMSSignature
from app.utils import process
from app.utils.logging import get_logger
from app.utils.paths import program_files_dirs

logger = get_logger(__name__)

_VERSION_PATTERN = re.compile(r"(\d+\.\d+(?:\.\d+)?)")
_PROGRAM_FILES_MAX_DEPTH = 4


class DetectionEngine:
    def __init__(self, service_manager: ServiceManager | None = None) -> None:
        self.service_manager = service_manager or ServiceManager()

    def detect_all(self) -> dict[DBMS, DetectionResult]:
        return {dbms: self.detect(dbms) for dbms in DBMS}

    def detect(self, dbms: DBMS) -> DetectionResult:
        signature = SIGNATURES[dbms]
        installations: list[Installation] = []

        services = self.service_manager.find_services(signature.service_name_patterns)
        running_service = next((s for s in services if s.state == "RUNNING"), None)
        any_service = services[0] if services else None

        server_paths = self._candidates(signature.server_executables, signature)
        for server_path in server_paths:
            if running_service is not None:
                status = DetectionStatus.SERVER_RUNNING
                service_name = running_service.name
            elif any_service is not None:
                status = DetectionStatus.SERVER_FOUND
                service_name = any_service.name
            else:
                status = DetectionStatus.SERVER_FOUND
                service_name = None
            installations.append(
                Installation(
                    dbms=dbms,
                    status=status,
                    version=self.get_version(server_path, signature.version_args),
                    executable_path=str(server_path),
                    service_name=service_name,
                )
            )

        # A client executable only counts on its own when no server
        # executable was found -- otherwise it would just duplicate
        # the server installation we already reported (Rule 5).
        if not server_paths:
            client_paths = self._candidates(signature.client_executables, signature)
            for client_path in client_paths:
                installations.append(
                    Installation(
                        dbms=dbms,
                        status=DetectionStatus.EXECUTABLE_FOUND,
                        version=self.get_version(client_path, signature.version_args),
                        executable_path=str(client_path),
                    )
                )

        return DetectionResult(dbms=dbms, installations=installations)

    def find_executables(self, base_names: tuple[str, ...]) -> list[Path]:
        """PATH-based discovery via shutil.which() (architecture.md signals 1-2)."""
        found: list[Path] = []
        for name in base_names:
            located = shutil.which(name)
            if located:
                found.append(Path(located))
        return found

    def find_in_program_files(
        self, base_names: tuple[str, ...], hint: str
    ) -> list[Path]:
        """Secondary discovery signal: scan Program Files folders whose name
        contains `hint` for one of `base_names`, bounded to a small depth.

        Exists because a database can be installed without its
        executable being added to PATH (05-prd.md risk: "PATH
        limitations") -- but this is still only a secondary signal
        (Rule 6): never treated as the only proof an installation
        exists, and never a single hardcoded path.
        """
        target_names = {self._exe_filename(name) for name in base_names}
        found: list[Path] = []
        for base in program_files_dirs():
            try:
                subdirs = [d for d in base.iterdir() if d.is_dir()]
            except OSError:
                continue
            for directory in subdirs:
                if hint.lower() not in directory.name.lower():
                    continue
                found.extend(self._search_dir(directory, target_names))
        return found

    @staticmethod
    def _search_dir(root: Path, target_names: set[str]) -> list[Path]:
        found: list[Path] = []
        root_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            depth = len(Path(dirpath).parts) - root_depth
            if depth >= _PROGRAM_FILES_MAX_DEPTH:
                dirnames[:] = []  # stop descending further
            for filename in filenames:
                if filename.lower() in target_names:
                    found.append(Path(dirpath) / filename)
        return found

    @staticmethod
    def _exe_filename(base_name: str) -> str:
        if platform.system() == "Windows":
            return f"{base_name}.exe".lower()
        return base_name.lower()

    def _candidates(
        self, base_names: tuple[str, ...], signature: DBMSSignature
    ) -> list[Path]:
        found = self.find_executables(base_names)
        found.extend(self.find_in_program_files(base_names, signature.program_files_hint))

        seen: set[Path] = set()
        unique: list[Path] = []
        for path in found:
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if resolved not in seen:
                seen.add(resolved)
                unique.append(path)
        return unique

    def get_version(self, executable: Path, version_args: tuple[str, ...]) -> str | None:
        """Best-effort version extraction.

        Returns None rather than raising if the executable can't be
        run or its output isn't recognized -- a version lookup must
        never abort detection. The regex is a generic first-version-
        number-in-output heuristic; Rule 9 requires this be verified
        against each real DBMS/version before later phases rely on it
        for more than a status-area hint.
        """
        try:
            result = process.run([str(executable), *version_args], timeout=5)
        except Exception as exc:  # missing binary, timeout, permission, etc.
            logger.debug(
                "Version check failed for %s: %s", executable, type(exc).__name__
            )
            return None

        output = f"{result.stdout}\n{result.stderr}"
        match = _VERSION_PATTERN.search(output)
        return match.group(1) if match else None
