"""
Main application window.

Layout and states follow 02-design.md: a DBMS dropdown, an
installation picker (shown only when multiple installations exist),
new/confirm password fields with show/hide, a Change Password button,
and a status area. All status/error wording lives in
app.gui.presentation, kept free of Qt so it's independently testable;
this module is only the Qt wiring.

Detection and password-change operations run on background QThreads
so the UI never blocks (02-design.md: "Show progress for operations
that take time").
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.adapters_registry import get_adapter
from app.core.detector import DetectionEngine
from app.core.models import DBMS, DetectionResult, Installation
from app.core.password_manager import (
    PasswordChangeRequest,
    ValidationError,
    change_password,
    validate,
)
from app.databases.base import DatabaseAdapter
from app.gui import presentation
from app.utils import elevation
from app.utils.logging import get_logger

logger = get_logger(__name__)


class _CallableWorker(QThread):
    """Runs a zero-argument callable off the UI thread and reports the
    outcome via a signal -- never lets an exception surface as a raw
    traceback in the GUI (02-design.md section 7)."""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[], object], parent=None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:  # noqa: BLE001 - translated for the UI, never re-raised
            logger.warning("Background operation failed: %s", type(exc).__name__)
            self.failed.emit(presentation.friendly_error(exc))
        else:
            self.succeeded.emit(result)


class MainWindow(QMainWindow):
    def __init__(
        self,
        detection_engine: DetectionEngine | None = None,
        adapter_factory: Callable[[DBMS], DatabaseAdapter] | None = None,
    ) -> None:
        super().__init__()
        self.detection_engine = detection_engine or DetectionEngine()
        self.adapter_factory = adapter_factory or get_adapter
        self._detection_results: dict[DBMS, DetectionResult] = {}
        self._detect_worker: _CallableWorker | None = None
        self._change_worker: _CallableWorker | None = None

        self.setWindowTitle("Setu — DB Password Reset Tool")
        self.resize(460, 360)

        self._build_ui()
        self._check_elevation()
        self._start_detection()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)

        heading = QLabel("DB Password Reset")
        heading.setStyleSheet("font-size: 16pt; font-weight: 600;")
        layout.addWidget(heading)

        self.elevation_label = QLabel()
        self.elevation_label.setWordWrap(True)
        self.elevation_label.setStyleSheet("color: #8a6100; font-weight: 500;")
        self.elevation_label.setAccessibleName("Elevation warning")
        self.elevation_label.setVisible(False)
        layout.addWidget(self.elevation_label)

        form = QFormLayout()

        self.database_combo = QComboBox()
        self.database_combo.setAccessibleName("Database")
        for dbms in DBMS:
            self.database_combo.addItem(str(dbms), dbms)
        db_label = QLabel("Database")
        db_label.setBuddy(self.database_combo)
        form.addRow(db_label, self.database_combo)

        self.installation_combo = QComboBox()
        self.installation_combo.setAccessibleName("Installation")
        self.installation_label = QLabel("Installation")
        self.installation_label.setBuddy(self.installation_combo)
        form.addRow(self.installation_label, self.installation_combo)
        self.installation_label.setVisible(False)
        self.installation_combo.setVisible(False)

        self.new_password_edit, new_password_row = self._password_field("New password")
        new_password_label = QLabel("New password")
        new_password_label.setBuddy(self.new_password_edit)
        form.addRow(new_password_label, new_password_row)

        self.confirm_password_edit, confirm_password_row = self._password_field(
            "Confirm password"
        )
        confirm_password_label = QLabel("Confirm password")
        confirm_password_label.setBuddy(self.confirm_password_edit)
        form.addRow(confirm_password_label, confirm_password_row)

        layout.addLayout(form)

        self.change_button = QPushButton("Change Password")
        self.change_button.clicked.connect(self._on_change_password_clicked)
        layout.addWidget(self.change_button)

        self.status_label = QLabel("Detecting installed databases…")
        self.status_label.setWordWrap(True)
        self.status_label.setAccessibleName("Status")
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.status_label)

        layout.addStretch(1)
        self.setCentralWidget(central)

        # Connected only once every widget it touches exists -- avoids
        # firing on the items added above, before installation_combo
        # (etc.) were built.
        self.database_combo.currentIndexChanged.connect(self._on_database_changed)

    def _password_field(self, placeholder: str) -> tuple[QLineEdit, QWidget]:
        edit = QLineEdit()
        edit.setEchoMode(QLineEdit.Password)
        edit.setPlaceholderText(placeholder)

        toggle = QPushButton("Show")
        toggle.setCheckable(True)
        toggle.setFixedWidth(56)
        toggle.setAccessibleName(f"Show {placeholder.lower()}")

        def _on_toggled(checked: bool) -> None:
            edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
            toggle.setText("Hide" if checked else "Show")

        toggle.toggled.connect(_on_toggled)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(edit)
        row_layout.addWidget(toggle)
        return edit, row

    # ------------------------------------------------------------------
    # Elevation
    # ------------------------------------------------------------------
    def _check_elevation(self) -> None:
        """Surface a non-elevated run up front (Rule 11/25): service
        control and config writes typically need Administrator rights,
        and failing partway through a reset is worse than warning before
        the user has typed a password."""
        message = elevation.elevation_warning()
        self.elevation_label.setText(message or "")
        self.elevation_label.setVisible(message is not None)

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------
    def _start_detection(self) -> None:
        self.change_button.setEnabled(False)
        self.status_label.setText("Detecting installed databases…")
        self._detect_worker = _CallableWorker(self.detection_engine.detect_all)
        self._detect_worker.succeeded.connect(self._on_detection_finished)
        self._detect_worker.failed.connect(self._on_detection_failed)
        self._detect_worker.start()

    def _on_detection_finished(self, results: object) -> None:
        self._detection_results = results  # type: ignore[assignment]
        self.change_button.setEnabled(True)
        self._on_database_changed()

    def _on_detection_failed(self, message: str) -> None:
        self.change_button.setEnabled(True)
        self.status_label.setText(f"Detection could not run: {message}")

    def _current_dbms(self) -> DBMS:
        return self.database_combo.currentData()

    def _on_database_changed(self, *_args: object) -> None:
        dbms = self._current_dbms()
        result = self._detection_results.get(dbms)

        self.installation_combo.clear()
        has_multiple = bool(result and result.has_multiple_installations)
        self.installation_label.setVisible(has_multiple)
        self.installation_combo.setVisible(has_multiple)
        if result:
            for installation in result.installations:
                label = (
                    installation.version
                    or installation.executable_path
                    or "Unknown installation"
                )
                self.installation_combo.addItem(label, installation)

        self.status_label.setText(presentation.status_text(dbms, result))

    def _selected_installation(self) -> Installation | None:
        if self.installation_combo.isVisible() and self.installation_combo.count():
            return self.installation_combo.currentData()
        return presentation.default_installation(self._current_dbms(), self._detection_results)

    # ------------------------------------------------------------------
    # Password change
    # ------------------------------------------------------------------
    def _on_change_password_clicked(self) -> None:
        dbms = self._current_dbms()
        installation = self._selected_installation()
        if installation is None:
            self.status_label.setText(
                f"Can't change the password: {dbms} was not detected on this machine."
            )
            return

        request = PasswordChangeRequest(
            installation=installation,
            new_password=self.new_password_edit.text(),
            confirm_password=self.confirm_password_edit.text(),
        )
        try:
            validate(request)
        except ValidationError as exc:
            self.status_label.setText(str(exc))
            return

        adapter = self.adapter_factory(dbms)
        self.change_button.setEnabled(False)
        self.status_label.setText(f"Changing {dbms} password…")

        self._change_worker = _CallableWorker(lambda: change_password(adapter, request))
        self._change_worker.succeeded.connect(self._on_change_finished)
        self._change_worker.failed.connect(self._on_change_failed)
        self._change_worker.start()

    def _on_change_finished(self, result: object) -> None:
        self.change_button.setEnabled(True)
        self.status_label.setText(
            presentation.operation_result_text(result.success, result.verified, result.message)
        )
        self.new_password_edit.clear()
        self.confirm_password_edit.clear()

    def _on_change_failed(self, message: str) -> None:
        self.change_button.setEnabled(True)
        self.status_label.setText(f"{presentation.CROSS} Password change failed.\n{message}")
        self.new_password_edit.clear()
        self.confirm_password_edit.clear()
