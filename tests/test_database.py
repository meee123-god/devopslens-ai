"""Unit tests for SQLite database operations and repository layer.

Verifies schema initialization, atomic transactions, foreign key cascade constraints,
and rollback behavior on failures.
"""

import pytest
from app.database.connection import get_db_connection
from app.services.analyzer import AnalysisResult, ErrorGroup
from app.services.parser import ParsedLogLine


def test_save_and_retrieve_analysis(test_repo):
    """Verify persisting an analysis and retrieving it with its error groups."""
    analysis_id = "ana_test_123"
    filename = "test_app.log"

    group = ErrorGroup(
        fingerprint="Connection error to <IP>",
        severity="ERROR",
        count=2,
        priority="P2 - High",
        score=85.0,
        sample_message="Connection error to 10.0.0.1",
        first_line=10,
        last_line=15,
        line_numbers=[10, 15],
        scoring_explanation="Base + Freq"
    )

    result = AnalysisResult(
        total_lines=100,
        debug_count=20,
        info_count=60,
        warning_count=10,
        error_count=8,
        critical_count=2,
        unstructured_count=0,
        error_groups=[group],
        lines=[]
    )

    # 1. Save
    saved = test_repo.save_analysis(
        analysis_id=analysis_id,
        filename=filename,
        result=result,
        execution_time_ms=12.5
    )
    assert saved["id"] == analysis_id
    assert saved["total_lines"] == 100

    # 2. Retrieve Analysis Summary
    retrieved = test_repo.get_analysis_by_id(analysis_id)
    assert retrieved is not None
    assert retrieved["filename"] == filename
    assert retrieved["error_count"] == 8

    # 3. Retrieve Error Groups
    groups = test_repo.get_error_groups(analysis_id)
    assert len(groups) == 1
    assert groups[0]["fingerprint"] == "Connection error to <IP>"
    assert groups[0]["line_numbers"] == [10, 15]


def test_get_analyses_pagination(test_repo):
    """Verify listing analyses with limit and offset."""
    for i in range(5):
        result = AnalysisResult(
            total_lines=10, debug_count=0, info_count=10, warning_count=0,
            error_count=0, critical_count=0, unstructured_count=0,
            error_groups=[], lines=[]
        )
        test_repo.save_analysis(f"ana_page_{i}", f"file_{i}.log", result, 1.0)

    # First page: limit 3
    page1 = test_repo.get_analyses(limit=3, offset=0)
    assert len(page1) == 3

    # Second page: limit 3, offset 3
    page2 = test_repo.get_analyses(limit=3, offset=3)
    assert len(page2) == 2


def test_foreign_key_cascade_delete(test_repo, temp_db_path):
    """Verify that deleting an analysis cascades to delete its error groups."""
    analysis_id = "ana_cascade_test"
    group = ErrorGroup(
        fingerprint="Disk full",
        severity="CRITICAL",
        count=1,
        priority="P1 - Critical",
        score=120.0,
        sample_message="Disk full",
        first_line=1,
        last_line=1,
        line_numbers=[1],
        scoring_explanation="Critical"
    )
    result = AnalysisResult(
        total_lines=1, debug_count=0, info_count=0, warning_count=0,
        error_count=0, critical_count=1, unstructured_count=0,
        error_groups=[group], lines=[]
    )

    test_repo.save_analysis(analysis_id, "disk.log", result, 5.0)

    # Confirm group exists
    assert len(test_repo.get_error_groups(analysis_id)) == 1

    # Delete parent analysis
    with get_db_connection(temp_db_path) as conn:
        conn.execute("DELETE FROM analyses WHERE id = ?;", (analysis_id,))

    # Confirm error_groups was also deleted via CASCADE
    assert len(test_repo.get_error_groups(analysis_id)) == 0


def test_transaction_rollback_on_failure(test_repo, temp_db_path):
    """Verify that a failed transaction rolls back cleanly without partial writes."""
    with pytest.raises(Exception):
        with get_db_connection(temp_db_path) as conn:
            conn.execute(
                "INSERT INTO analyses (id, filename, uploaded_at, total_lines, debug_count, info_count, warning_count, error_count, critical_count, unstructured_count, status, execution_time_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                ("ana_fail", "fail.log", "2026-10-29T00:00:00Z", 10, 0, 10, 0, 0, 0, 0, "COMPLETED", 1.0)
            )
            # Intentionally cause a foreign key or SQL syntax violation
            conn.execute("INSERT INTO non_existent_table VALUES (1, 2);")

    # Verify ana_fail was rolled back
    assert test_repo.get_analysis_by_id("ana_fail") is None
