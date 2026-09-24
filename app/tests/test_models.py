from app.core.models import DBMS, DetectionResult, DetectionStatus, Installation


def test_detection_result_not_detected_by_default():
    result = DetectionResult(dbms=DBMS.MYSQL)
    assert result.status == DetectionStatus.NOT_DETECTED
    assert not result.has_multiple_installations


def test_detection_result_reports_most_confirmed_status():
    installations = [
        Installation(dbms=DBMS.POSTGRESQL, status=DetectionStatus.EXECUTABLE_FOUND),
        Installation(dbms=DBMS.POSTGRESQL, status=DetectionStatus.SERVER_RUNNING),
    ]
    result = DetectionResult(dbms=DBMS.POSTGRESQL, installations=installations)
    assert result.status == DetectionStatus.SERVER_RUNNING
    assert result.has_multiple_installations
