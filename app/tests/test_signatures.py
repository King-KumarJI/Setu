from app.core.models import DBMS
from app.core.signatures import SIGNATURES


def test_every_dbms_has_a_signature():
    for dbms in DBMS:
        assert dbms in SIGNATURES


def test_signatures_have_non_empty_candidates():
    for signature in SIGNATURES.values():
        assert signature.client_executables
        assert signature.server_executables
        assert signature.service_name_patterns
        assert signature.program_files_hint
        assert signature.version_args
