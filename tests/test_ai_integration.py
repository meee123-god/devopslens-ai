"""Unit and integration tests for AI-assisted triage and evidence validation.

Verifies deterministic offline heuristic diagnosis, evidence grounding verification,
and graceful fallback handling when external AI calls timeout or return errors.
"""

from unittest.mock import MagicMock, patch
import httpx
import pytest

from app.ai.client import AIDiagnosisClient
from app.ai.validator import verify_and_sanitize_diagnosis
from app.config import Settings


def test_heuristic_database_error_diagnosis():
    """Verify built-in heuristic diagnosis accurately identifies database connection failure."""
    client = AIDiagnosisClient()
    lines = [
        "2026-10-29 10:00:00 [ERROR] Database connection pool exhausted: 50/50 active connections.",
        "2026-10-29 10:00:01 [ERROR] Transaction rollback on order #4019"
    ]

    diag = client.diagnose_issue(
        error_message="Database connection pool exhausted: 50/50 active connections.",
        severity="ERROR",
        occurrence_count=5,
        surrounding_lines=lines
    )

    assert "database" in diag.probable_cause.lower() or "pool" in diag.probable_cause.lower()
    assert len(diag.debugging_steps) > 0
    assert "High" in diag.confidence
    assert "hypothesis" in diag.limitations.lower()
    assert len(diag.supporting_evidence) > 0
    # Verifies cited evidence actually matches the input
    assert any("database" in ev.lower() for ev in diag.supporting_evidence)


def test_heuristic_memory_error_diagnosis():
    """Verify built-in heuristic diagnosis accurately identifies OutOfMemory errors."""
    client = AIDiagnosisClient()
    lines = [
        "2026-10-29 10:00:00 [CRITICAL] java.lang.OutOfMemoryError: Java heap space"
    ]

    diag = client.diagnose_issue(
        error_message="java.lang.OutOfMemoryError: Java heap space",
        severity="CRITICAL",
        occurrence_count=1,
        surrounding_lines=lines
    )

    assert "memory" in diag.probable_cause.lower() or "heap" in diag.probable_cause.lower()
    assert any("heap" in s.lower() or "memory" in s.lower() for s in diag.debugging_steps)


def test_evidence_validator_detects_hallucinations():
    """Verify that claims not present in supplied log lines are tagged as unverified."""
    supplied = [
        "Line 10: Connection to PostgreSQL timed out at 10.0.4.12:5432",
        "Line 11: Retrying database handshake"
    ]

    raw_ai_output = {
        "probable_cause": "Database connection drop",
        "supporting_evidence": [
            "Connection to PostgreSQL timed out at 10.0.4.12:5432",  # Real match
            "Fabricated log line about Redis cache miss"            # Hallucinated line
        ],
        "debugging_steps": ["Check network connection."],
        "confidence": "High",
        "limitations": "Automated hypothesis."
    }

    validated = verify_and_sanitize_diagnosis(
        raw_data=raw_ai_output,
        supplied_lines=supplied,
        model_name="test-model"
    )

    # Real match is preserved
    assert "Connection to PostgreSQL timed out at 10.0.4.12:5432" in validated.supporting_evidence[0]
    # Hallucinated line is tagged
    assert "[Unverified citation]" in validated.supporting_evidence[1]
    # Confidence reflects the discrepancy
    assert "Warning" in validated.confidence


def test_external_ai_timeout_fallback_to_heuristic(monkeypatch):
    """Verify that an external AI request timeout gracefully falls back to heuristic engine."""
    client = AIDiagnosisClient()

    # Configure client to act as if external AI is enabled
    mock_settings = Settings(
        ai_provider="gemini",
        ai_api_key="mock_secret_key_12345",
        ai_request_timeout_seconds=1.0
    )
    monkeypatch.setattr(client, "settings", mock_settings)

    # Mock httpx.Client to raise TimeoutException
    with patch("httpx.Client.post", side_effect=httpx.TimeoutException("Read timed out")):
        diag = client.diagnose_issue(
            error_message="Connection to database host timed out",
            severity="ERROR",
            occurrence_count=3,
            surrounding_lines=["Connection to database host timed out"]
        )

        # Fallback should succeed without throwing an uncaught exception
        assert diag is not None
        assert "database" in diag.probable_cause.lower()
        assert "External AI unavailable" in diag.limitations


def test_external_ai_http_500_fallback(monkeypatch):
    """Verify that external provider 500 server error triggers safe fallback."""
    client = AIDiagnosisClient()

    mock_settings = Settings(
        ai_provider="openai",
        ai_api_key="mock_secret_key_12345",
        ai_request_timeout_seconds=2.0
    )
    monkeypatch.setattr(client, "settings", mock_settings)

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        message="500 Internal Server Error",
        request=MagicMock(),
        response=mock_response
    )

    with patch("httpx.Client.post", return_value=mock_response):
        diag = client.diagnose_issue(
            error_message="Unauthorized access token",
            severity="ERROR",
            occurrence_count=2,
            surrounding_lines=["Unauthorized access token"]
        )

        assert diag is not None
        assert "External AI unavailable" in diag.limitations
