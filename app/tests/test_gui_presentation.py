"""
Tests for app.gui.presentation -- deliberately does not import
PySide6 (nor anything under app.gui.main_window), so this suite runs
even where PySide6 can't be installed. Qt widget behavior itself
still needs a manual check on a real desktop.
"""
from app.core.models import DBMS, DetectionResult, DetectionStatus, Installation
from app.gui import presentation


def test_status_text_not_detected_when_no_result():
    assert presentation.status_text(DBMS.REDIS, None) == "✕ Redis not detected"


def test_status_text_not_detected_when_empty_result():
    result = DetectionResult(dbms=DBMS.REDIS)
    text = presentation.status_text(DBMS.REDIS, result)
    assert text.startswith("✕")
    assert "not detected" in text


def test_status_text_executable_found():
    result = DetectionResult(
        dbms=DBMS.MYSQL,
        installations=[
            Installation(dbms=DBMS.MYSQL, status=DetectionStatus.EXECUTABLE_FOUND)
        ],
    )
    text = presentation.status_text(DBMS.MYSQL, result)
    assert text.startswith("⚠")
    assert "could not be confirmed" in text


def test_status_text_server_running_includes_version():
    result = DetectionResult(
        dbms=DBMS.POSTGRESQL,
        installations=[
            Installation(
                dbms=DBMS.POSTGRESQL, status=DetectionStatus.SERVER_RUNNING, version="16"
            )
        ],
    )
    text = presentation.status_text(DBMS.POSTGRESQL, result)
    assert text.startswith("✓")
    assert "Version: 16" in text
    assert "Running" in text


def test_status_text_notes_multiple_installations():
    result = DetectionResult(
        dbms=DBMS.MYSQL,
        installations=[
            Installation(dbms=DBMS.MYSQL, status=DetectionStatus.SERVER_RUNNING, version="8.0"),
            Installation(dbms=DBMS.MYSQL, status=DetectionStatus.SERVER_FOUND, version="5.7"),
        ],
    )
    text = presentation.status_text(DBMS.MYSQL, result)
    assert "Multiple installations detected" in text


def test_friendly_error_names_not_implemented_case():
    message = presentation.friendly_error(NotImplementedError("MySQL detection lands in Phase 3."))
    assert "isn't supported yet" in message
    assert "Phase 3" not in message  # internal detail shouldn't leak to the user


def test_friendly_error_falls_back_for_other_exceptions():
    message = presentation.friendly_error(ValueError("boom"))
    assert "Something went wrong" in message
    assert "boom" in message


def test_default_installation_returns_none_when_not_detected():
    assert presentation.default_installation(DBMS.REDIS, {}) is None


def test_default_installation_returns_first_installation():
    installation = Installation(dbms=DBMS.MYSQL, status=DetectionStatus.SERVER_RUNNING)
    results = {DBMS.MYSQL: DetectionResult(dbms=DBMS.MYSQL, installations=[installation])}
    assert presentation.default_installation(DBMS.MYSQL, results) is installation


def test_operation_result_text_success_and_verified():
    text = presentation.operation_result_text(True, True, "done")
    assert text.startswith("✓")
    assert "verified" in text


def test_operation_result_text_success_but_unverified():
    text = presentation.operation_result_text(True, False, "done")
    assert text.startswith("⚠")
    assert "could not be verified" in text


def test_operation_result_text_failure():
    text = presentation.operation_result_text(False, False, "server unreachable")
    assert text.startswith("✕")
    assert "failed" in text
