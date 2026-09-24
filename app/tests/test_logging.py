import io
import logging

from app.utils.logging import clear_secrets, get_logger, register_secret


def test_registered_secret_is_redacted_from_log_output():
    clear_secrets()
    logger = get_logger("setu.tests.secret-redaction")

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.INFO)
    logger.addHandler(handler)

    try:
        register_secret("SuperSecretPW123")
        logger.info("changing password to %s", "SuperSecretPW123")
    finally:
        logger.removeHandler(handler)
        clear_secrets()

    output = stream.getvalue()
    assert "SuperSecretPW123" not in output
    assert "REDACTED" in output
