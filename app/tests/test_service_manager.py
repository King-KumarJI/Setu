from app.core.service_manager import ServiceInfo, ServiceManager

SAMPLE_SC_OUTPUT = """
SERVICE_NAME: MySQL80
DISPLAY_NAME: MySQL80
        TYPE               : 10  WIN32_OWN_PROCESS
        STATE              : 4  RUNNING
                                (STOPPABLE, PAUSABLE, ACCEPTS_SHUTDOWN)
        WIN32_EXIT_CODE    : 0  (0x0)
        SERVICE_EXIT_CODE  : 0  (0x0)
        CHECKPOINT         : 0x0
        WAIT_HINT          : 0x0

SERVICE_NAME: postgresql-x64-16
DISPLAY_NAME: postgresql-x64-16 - PostgreSQL Server 16
        TYPE               : 10  WIN32_OWN_PROCESS
        STATE              : 1  STOPPED
        WIN32_EXIT_CODE    : 0  (0x0)
        SERVICE_EXIT_CODE  : 0  (0x0)
        CHECKPOINT         : 0x0
        WAIT_HINT          : 0x0
"""


def test_parse_sc_query_output_extracts_services():
    services = ServiceManager._parse_sc_query_output(SAMPLE_SC_OUTPUT)
    assert services == [
        ServiceInfo(name="MySQL80", display_name="MySQL80", state="RUNNING"),
        ServiceInfo(
            name="postgresql-x64-16",
            display_name="postgresql-x64-16 - PostgreSQL Server 16",
            state="STOPPED",
        ),
    ]


def test_find_services_matches_case_insensitive_substring(monkeypatch):
    manager = ServiceManager()
    services = ServiceManager._parse_sc_query_output(SAMPLE_SC_OUTPUT)
    monkeypatch.setattr(manager, "list_services", lambda: services)

    matches = manager.find_services(("mysql",))
    assert [s.name for s in matches] == ["MySQL80"]


def test_find_services_returns_empty_when_nothing_matches(monkeypatch):
    manager = ServiceManager()
    services = ServiceManager._parse_sc_query_output(SAMPLE_SC_OUTPUT)
    monkeypatch.setattr(manager, "list_services", lambda: services)

    assert manager.find_services(("mongodb",)) == []


def test_list_services_returns_empty_on_non_windows(monkeypatch):
    manager = ServiceManager()
    monkeypatch.setattr("app.core.service_manager.platform.system", lambda: "Linux")
    assert manager.list_services() == []
