import pytest

from app.databases.base import DatabaseAdapter


def test_database_adapter_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        DatabaseAdapter()
