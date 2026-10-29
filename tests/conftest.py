"""Pytest fixtures for DevOpsLens AI test suite.

Provides isolated temporary databases, FastAPI test clients, and reusable log fixtures.
"""

import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.database.connection import init_db
from app.database.repository import AnalysisRepository
from app.main import app


@pytest.fixture
def temp_db_path():
    """Create a unique temporary database file for test isolation."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(custom_path=path)
    yield path
    # Teardown
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


@pytest.fixture
def test_repo(temp_db_path):
    """Provide an AnalysisRepository backed by the isolated temporary database."""
    return AnalysisRepository(db_path=temp_db_path)


@pytest.fixture
def client(temp_db_path, monkeypatch):
    """Provide a FastAPI TestClient configured to use the isolated test database."""
    # Override settings to point to temp_db_path
    def get_test_settings():
        return Settings(
            database_path=temp_db_path,
            ai_provider="offline",
            environment="testing"
        )

    # Override dependency and connection path
    from app.api import routes
    routes.get_repository = lambda: AnalysisRepository(db_path=temp_db_path)

    app.dependency_overrides[get_settings] = get_test_settings

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def sample_log_text():
    """Sample realistic log with multiple severities and recurring errors."""
    return """
2026-10-29 10:00:00 [DEBUG] Initializing worker thread pool.
2026-10-29 10:00:01 [INFO] Server listening on port 8080.
2026-10-29 10:00:05 [WARNING] High memory usage: 78% of 4096MB utilized.
2026-10-29 10:00:10 [ERROR] Database connection failed to host 10.0.0.15:5432 with timeout.
2026-10-29 10:00:12 [ERROR] Database connection failed to host 10.0.0.18:5432 with timeout.
2026-10-29 10:00:15 [CRITICAL] Fatal system error: OutOfMemoryError in queue processor.
Unstructured traceback line without metadata
""".strip()
