"""Unit tests for the log parsing service (LogParser).

Verifies severity level mapping, timestamp patterns, component extraction,
and resilience against unstructured log entries.
"""

from app.services.parser import LogParser


def test_parse_all_severity_levels():
    """Verify parser identifies and standardizes every supported severity level."""
    parser = LogParser()
    test_lines = [
        ("2026-10-29 10:00:00 [DEBUG] Starting debug mode", "DEBUG"),
        ("2026-10-29 10:00:01 [INFO] Service started", "INFO"),
        ("2026-10-29 10:00:02 [WARN] High memory", "WARNING"),
        ("2026-10-29 10:00:03 [WARNING] Disk slow", "WARNING"),
        ("2026-10-29 10:00:04 [ERROR] Connection lost", "ERROR"),
        ("2026-10-29 10:00:05 [CRIT] Kernel panic", "CRITICAL"),
        ("2026-10-29 10:00:06 [CRITICAL] Out of memory", "CRITICAL"),
        ("2026-10-29 10:00:07 [FATAL] Process aborted", "CRITICAL"),
    ]

    for line_text, expected_severity in test_lines:
        parsed = parser.parse_line(line_text, line_number=1)
        assert parsed.severity == expected_severity, f"Failed on: {line_text}"


def test_parse_timestamp_formats():
    """Verify ISO, Apache, and Syslog timestamp extraction."""
    parser = LogParser()

    # ISO-8601
    p1 = parser.parse_line("2026-10-29 14:22:31,456 [INFO] Started", 1)
    assert p1.timestamp == "2026-10-29 14:22:31,456"

    # Apache / Common Log format
    p2 = parser.parse_line('[29/Oct/2026:14:22:31 +0000] "GET /index.html" 200', 2)
    assert p2.timestamp == "29/Oct/2026:14:22:31 +0000"

    # Syslog format
    p3 = parser.parse_line("Oct 29 14:22:31 server-01 kernel: [ERROR] Disk error", 3)
    assert p3.timestamp == "Oct 29 14:22:31"

    # Missing timestamp
    p4 = parser.parse_line("Raw message without timestamp", 4)
    assert p4.timestamp is None


def test_parse_component_extraction():
    """Verify bracketed and parenthesized component / service name extraction."""
    parser = LogParser()

    p1 = parser.parse_line("2026-10-29 10:00:00 [auth-service] [INFO] User logged in", 1)
    assert p1.component == "auth-service"

    p2 = parser.parse_line("2026-10-29 10:00:00 (database_pool) [ERROR] Timeout", 2)
    assert p2.component == "database_pool"


def test_parse_unstructured_and_stack_trace_lines():
    """Verify that unstructured lines, stack traces, and raw lines do not crash the parser."""
    parser = LogParser()

    traceback_line = '  File "/app/server.py", line 42, in process_request'
    parsed = parser.parse_line(traceback_line, line_number=10)

    assert parsed.line_number == 10
    assert parsed.severity == "UNSTRUCTURED"
    assert "File \"/app/server.py\"" in parsed.message
    assert parsed.raw_line == traceback_line


def test_parse_text_preserves_line_numbers():
    """Verify that parsing a multi-line document preserves 1-based line numbers."""
    parser = LogParser()
    text = "Line one\nLine two\nLine three\nLine four"
    results = parser.parse_text(text)

    assert len(results) == 4
    for idx, r in enumerate(results, start=1):
        assert r.line_number == idx
