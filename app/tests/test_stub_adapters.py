from app.core.models import DBMS
from app.databases.mariadb import MariaDBAdapter
from app.databases.mongodb import MongoDBAdapter
from app.databases.mysql import MySQLAdapter
from app.databases.postgresql import PostgreSQLAdapter
from app.databases.redis import RedisAdapter

# All five adapters are implemented as of Phase 5 -- this file now
# only checks the one thing every adapter must still get right: it
# declares the DBMS it belongs to. Each adapter's real behavior is
# covered by its own dedicated test module.
ALL_ADAPTERS = [
    (MySQLAdapter, DBMS.MYSQL),
    (PostgreSQLAdapter, DBMS.POSTGRESQL),
    (MariaDBAdapter, DBMS.MARIADB),
    (MongoDBAdapter, DBMS.MONGODB),
    (RedisAdapter, DBMS.REDIS),
]


def test_every_adapter_declares_correct_dbms():
    for adapter_cls, expected_dbms in ALL_ADAPTERS:
        assert adapter_cls.dbms == expected_dbms
