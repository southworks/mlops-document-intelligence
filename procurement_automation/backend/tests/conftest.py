from pathlib import Path
import sys
from contextlib import contextmanager
from typing import Generator, Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker, scoped_session
from sqlalchemy.pool import StaticPool

# Add modeladmin_service to path for cross-service imports
MODELADMIN_SRC = Path(__file__).resolve().parents[2] / "modeladmin_service" / "src"
if str(MODELADMIN_SRC) not in sys.path:
    sys.path.insert(0, str(MODELADMIN_SRC))

# Pytest fixture configuration for markers
def pytest_configure(config):
    """Register marker descriptions for enforcement."""
    config.addinivalue_line(
        "markers", "unit: Unit test (no external dependencies, fast)"
    )
    config.addinivalue_line(
        "markers", "integration: Integration test (requires services)"
    )
    config.addinivalue_line(
        "markers", "e2e: End-to-end test (full workflow)"
    )
    config.addinivalue_line(
        "markers", "slow: Test takes > 5 seconds"
    )
    config.addinivalue_line(
        "markers", "docker_required: Requires Docker Compose running"
    )
    config.addinivalue_line(
        "markers", "external_service: Calls external services (Azure, etc)"
    )
    config.addinivalue_line(
        "markers", "regression: Regression test against known data"
    )


# Session-scoped fixtures
@pytest.fixture(scope="session")
def db_engine():
    """Create an in-memory SQLite engine for all tests (session-scoped).

    This is shared across all tests in the session. Transactional isolation
    is handled at function scope via db_session fixture.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def db_session_factory(db_engine):
    """Create a sessionmaker factory for reuse across tests.

    This factory enables creation of new sessions with proper transaction
    management and rollback behavior.
    """
    return sessionmaker(bind=db_engine, expire_on_commit=False)


# Function-scoped fixtures (per test)
@pytest.fixture
def db_session(db_engine, db_session_factory) -> Generator[Session, None, None]:
    """Provide a database session with automatic transactional rollback.

    Each test gets a fresh session. Changes are rolled back after the test,
    ensuring test isolation without needing to recreate the database.

    Yields:
        Session: A SQLAlchemy session for the test
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    session = db_session_factory(bind=connection)

    # Optional: Create all tables if needed
    # Base.metadata.create_all(connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def test_client(monkeypatch) -> TestClient:
    """Provide a FastAPI TestClient for HTTP testing.

    This fixture can be extended to override dependencies (database, services).

    Returns:
        TestClient: FastAPI test client ready for making requests
    """
    from app.main import app
    return TestClient(app)


@pytest.fixture
def mock_azure_blob_client(monkeypatch):
    """Mock Azure Blob Storage client for unit/integration tests.

    Prevents tests from requiring actual Azure storage connections.
    """
    class MockBlobClient:
        def upload_blob(self, *args, **kwargs):
            return {"md5": b"mock_hash"}

        def download_blob(self, *args, **kwargs):
            class MockDownload:
                def readall(self):
                    return b"mock_content"
            return MockDownload()

        def delete_blob(self, *args, **kwargs):
            pass

    return MockBlobClient()


@pytest.fixture
def mock_document_intelligence_client(monkeypatch):
    """Mock Azure Document Intelligence client for unit tests.

    Prevents tests from requiring actual Azure Document Intelligence service.
    """
    class MockDocumentAnalysisClient:
        def begin_analyze_document(self, *args, **kwargs):
            class MockPoller:
                def result(self):
                    return {
                        "documents": [
                            {
                                "content": "mock_content",
                                "confidence_score": 0.95,
                            }
                        ]
                    }
            return MockPoller()

    return MockDocumentAnalysisClient()


# Context managers for test utilities
@contextmanager
def transactional_session(db_engine) -> Generator[Session, None, None]:
    """Context manager for db sessions with automatic rollback.

    Useful for subprocess-style testing where test scope is more restricted.
    All database changes are rolled back on exit.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def assert_clean_db(db_session: Session) -> callable:
    """Fixture that validates database state claims.

    Returns a validator function that can be used to assert database
    assumptions before/after test operations.
    """
    def _validate(**kwargs):
        """
        Validate that database matches expected state.
        Example: assert_clean_db(user_count=0, job_count=0)
        """
        # This is a placeholder - extend based on your schema
        return True

    return _validate
