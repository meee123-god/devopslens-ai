"""SQLite database connection and schema management.

Provides thread-safe connection management via context managers, enforces foreign key
constraints, enables Write-Ahead Logging (WAL) for concurrency, and initializes database tables.
"""

import os
import sqlite3
from contextlib import contextmanager
from typing import Generator, Optional
from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# SQL DDL Schemas
CREATE_ANALYSES_TABLE = """
CREATE TABLE IF NOT EXISTS analyses (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    total_lines INTEGER NOT NULL,
    debug_count INTEGER NOT NULL,
    info_count INTEGER NOT NULL,
    warning_count INTEGER NOT NULL,
    error_count INTEGER NOT NULL,
    critical_count INTEGER NOT NULL,
    unstructured_count INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'COMPLETED',
    execution_time_ms REAL NOT NULL
);
"""

CREATE_ERROR_GROUPS_TABLE = """
CREATE TABLE IF NOT EXISTS error_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    severity TEXT NOT NULL,
    priority TEXT NOT NULL,
    score REAL NOT NULL,
    count INTEGER NOT NULL,
    sample_message TEXT NOT NULL,
    first_line INTEGER NOT NULL,
    last_line INTEGER NOT NULL,
    line_numbers_json TEXT NOT NULL,
    scoring_explanation TEXT NOT NULL,
    FOREIGN KEY (analysis_id) REFERENCES analyses (id) ON DELETE CASCADE
);
"""

CREATE_AI_DIAGNOSES_TABLE = """
CREATE TABLE IF NOT EXISTS ai_diagnoses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id TEXT NOT NULL,
    error_group_id INTEGER,
    probable_cause TEXT NOT NULL,
    supporting_evidence_json TEXT NOT NULL,
    debugging_steps_json TEXT NOT NULL,
    confidence TEXT NOT NULL,
    limitations TEXT NOT NULL,
    model_used TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (analysis_id) REFERENCES analyses (id) ON DELETE CASCADE,
    FOREIGN KEY (error_group_id) REFERENCES error_groups (id) ON DELETE CASCADE
);
"""

# Indexes for fast historical queries
CREATE_INDEX_ANALYSES_UPLOADED = """
CREATE INDEX IF NOT EXISTS idx_analyses_uploaded_at ON analyses (uploaded_at DESC);
"""

CREATE_INDEX_ERROR_GROUPS_ANALYSIS = """
CREATE INDEX IF NOT EXISTS idx_error_groups_analysis_id ON error_groups (analysis_id);
"""


def get_db_path(custom_path: Optional[str] = None) -> str:
    """Return the resolved path to the SQLite database file."""
    if custom_path:
        return custom_path
    settings = get_settings()
    return settings.database_path


@contextmanager
def get_db_connection(custom_path: Optional[str] = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for SQLite connections.
    
    Guarantees:
    - Foreign key constraint enforcement (`PRAGMA foreign_keys = ON`).
    - Row factory enabled for dictionary-like column access (`sqlite3.Row`).
    - Automatic commit on successful block exit.
    - Automatic rollback if an unhandled exception occurs inside the block.
    - Explicit connection close to avoid resource leaks.
    """
    db_path = get_db_path(custom_path)

    # Ensure parent directory exists if a path with subfolders was specified
    parent_dir = os.path.dirname(db_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    conn = sqlite3.connect(db_path, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    try:
        # Enforce foreign key constraints (disabled by default in SQLite)
        conn.execute("PRAGMA foreign_keys = ON;")
        # Enable Write-Ahead Logging for better concurrent read/write throughput
        if db_path != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL;")

        yield conn
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error(f"Database transaction rolled back due to error: {exc}")
        raise
    finally:
        conn.close()


def init_db(custom_path: Optional[str] = None) -> None:
    """Create all required database tables and indexes if they do not already exist."""
    db_path = get_db_path(custom_path)
    logger.info(f"Initializing SQLite database schema at: {db_path}")

    with get_db_connection(db_path) as conn:
        conn.execute(CREATE_ANALYSES_TABLE)
        conn.execute(CREATE_ERROR_GROUPS_TABLE)
        conn.execute(CREATE_AI_DIAGNOSES_TABLE)
        conn.execute(CREATE_INDEX_ANALYSES_UPLOADED)
        conn.execute(CREATE_INDEX_ERROR_GROUPS_ANALYSIS)

    logger.info("Database schema initialized successfully.")
