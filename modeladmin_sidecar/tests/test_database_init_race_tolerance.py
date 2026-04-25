# pylint: disable=wrong-import-position

import os
import sqlite3

from sqlalchemy.exc import OperationalError

os.environ.setdefault(
    "AZURE_STORAGE_CONNECTION_STRING",
    "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey="
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
    "QueueEndpoint=http://127.0.0.1:10001/devstoreaccount1;"
    "TableEndpoint=http://127.0.0.1:10002/devstoreaccount1;"
)

from modeladmin_sidecar.database import connection


class _DummyResult:
    def fetchall(self):
        return []


class _DummyConn:
    def execute(self, _):
        return _DummyResult()


class _DummyBegin:
    def __enter__(self):
        return _DummyConn()

    def __exit__(self, exc_type, exc, tb):
        return False


class _DummyEngine:
    def begin(self):
        return _DummyBegin()


def test_init_db_propagates_unexpected_operational_errors(monkeypatch):
    """init_db does not swallow unexpected OperationalErrors (retry logic was removed)."""

    def broken_create_all(*_, **__):
        raise OperationalError(
            "CREATE TABLE training_datasets (...)",
            {},
            sqlite3.OperationalError("table training_datasets already exists"),
        )

    monkeypatch.setattr(connection, "DATABASE_URL", "sqlite:///./modeladmin-race-test.db")
    monkeypatch.setattr(connection, "engine", _DummyEngine())
    monkeypatch.setattr(connection.Base.metadata, "create_all", broken_create_all)

    try:
        connection.init_db()
        assert False, "Expected OperationalError to propagate"
    except OperationalError:
        pass  # expected
