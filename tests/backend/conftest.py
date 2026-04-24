# Copied from original location. See backend/tests/conftest.py for full fixture and marker setup.

import sys
from pathlib import Path
from contextlib import contextmanager
from typing import Generator, Optional

# Ensure repo root is in sys.path for all tests
REPO_ROOT = str(Path(__file__).resolve().parents[2])
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker, scoped_session
from sqlalchemy.pool import StaticPool

MODELADMIN_SRC = Path(__file__).resolve().parents[2] / "modeladmin_service" / "src"
if str(MODELADMIN_SRC) not in sys.path:
    sys.path.insert(0, str(MODELADMIN_SRC))

def pytest_configure(config):
    config.addinivalue_line("markers", "unit: Unit test (no external dependencies, fast)")
    config.addinivalue_line("markers", "integration: Integration test (requires services)")
    config.addinivalue_line("markers", "e2e: End-to-end test (full workflow)")
    config.addinivalue_line("markers", "slow: Test takes > 5 seconds")
    config.addinivalue_line("markers", "docker_required: Requires Docker Compose running")
    config.addinivalue_line("markers", "external_service: Calls external services (Azure, etc)")
    config.addinivalue_line("markers", "regression: Regression test against known data")

@pytest.fixture(scope="session")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    yield engine
    engine.dispose()
