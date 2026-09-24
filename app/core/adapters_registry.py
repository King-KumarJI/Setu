"""
Maps each DBMS to its adapter class.

The GUI (and anything else that needs an adapter) goes through
get_adapter() rather than importing a specific class, so adding a
DBMS never requires touching GUI code (Rule 7 / Rule 8).
"""
from __future__ import annotations

from app.core.models import DBMS
from app.databases.base import DatabaseAdapter
from app.databases.mariadb import MariaDBAdapter
from app.databases.mongodb import MongoDBAdapter
from app.databases.mysql import MySQLAdapter
from app.databases.postgresql import PostgreSQLAdapter
from app.databases.redis import RedisAdapter

ADAPTER_CLASSES: dict[DBMS, type[DatabaseAdapter]] = {
    DBMS.MYSQL: MySQLAdapter,
    DBMS.POSTGRESQL: PostgreSQLAdapter,
    DBMS.MARIADB: MariaDBAdapter,
    DBMS.MONGODB: MongoDBAdapter,
    DBMS.REDIS: RedisAdapter,
}


def get_adapter(dbms: DBMS) -> DatabaseAdapter:
    """Instantiate the production adapter for one DBMS.

    Every adapter class today is a Phase 0 scaffold that raises
    NotImplementedError on real operations (Phase 3 replaces MySQL,
    Phase 4 PostgreSQL, Phase 5 the rest) -- the GUI catches that and
    shows a friendly "not supported yet" message rather than crash.
    """
    return ADAPTER_CLASSES[dbms]()
