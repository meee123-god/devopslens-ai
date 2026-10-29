"""Unit tests for the log analysis and ranking service (LogAnalyzer).

Verifies dynamic fingerprinting, recurring error grouping, and the transparent
rule-based severity ranking calculations.
"""

from app.services.analyzer import LogAnalyzer
from app.services.parser import LogParser


def test_fingerprint_normalization():
    """Verify that dynamic identifiers (IPs, UUIDs, hex, numbers) are normalized into tokens."""
    analyzer = LogAnalyzer()

    # Dynamic IP and port
    msg1 = "Connection failed to 192.168.1.100:5432 after 30 seconds"
    msg2 = "Connection failed to 10.0.0.5:5432 after 45 seconds"
    fp1 = analyzer.generate_fingerprint(msg1)
    fp2 = analyzer.generate_fingerprint(msg2)
    assert fp1 == fp2
    assert "<IP>" in fp1
    assert "<NUM>" in fp1

    # UUIDs
    uuid_msg = "Order c8d3a950-891a-4d2b-bb42-123456789abc not found"
    fp_uuid = analyzer.generate_fingerprint(uuid_msg)
    assert "<UUID>" in fp_uuid


def test_recurring_error_grouping():
    """Verify that multiple occurrences of an error with varying dynamic IDs group together."""
    parser = LogParser()
    analyzer = LogAnalyzer()

    raw_log = """
2026-10-29 10:00:01 [ERROR] Failed to query user 101 from host 192.168.0.1
2026-10-29 10:00:02 [ERROR] Failed to query user 102 from host 192.168.0.2
2026-10-29 10:00:03 [ERROR] Failed to query user 103 from host 192.168.0.3
2026-10-29 10:00:04 [INFO] Normal ping
""".strip()

    parsed = parser.parse_text(raw_log)
    result = analyzer.analyze(parsed)

    assert result.total_lines == 4
    assert result.error_count == 3
    assert result.info_count == 1
    assert len(result.error_groups) == 1

    group = result.error_groups[0]
    assert group.count == 3
    assert group.first_line == 1
    assert group.last_line == 3
    assert group.line_numbers == [1, 2, 3]


def test_transparent_priority_scoring_rules():
    """Verify transparent priority calculation tiers and components."""
    analyzer = LogAnalyzer()

    # Case 1: Critical with DB keyword and high occurrences -> P1 - Critical
    # Base: 100, Freq: min(10*3, 40)=30, Keyword 'database': 15 -> Total: 145 -> P1
    p1, score1, expl1 = analyzer.calculate_priority(
        severity="CRITICAL",
        count=10,
        sample_message="Database master node crashed"
    )
    assert p1 == "P1 - Critical"
    assert score1 >= 110.0
    assert "Base severity" in expl1
    assert "Critical keyword boost" in expl1

    # Case 2: Single standard error without critical keywords -> P2 - High or P3 - Medium
    # Base: 60, Freq: 1*3=3, Keyword: 0 -> Total: 63 -> P3 - Medium
    p2, score2, _ = analyzer.calculate_priority(
        severity="ERROR",
        count=1,
        sample_message="Template rendering syntax problem"
    )
    assert p2 == "P3 - Medium"
    assert score2 == 63.0

    # Case 3: Sporadic warning -> P4 - Low
    # Base: 30, Freq: 1*3=3 -> Total: 33 -> P4 - Low
    p4, score4, _ = analyzer.calculate_priority(
        severity="WARNING",
        count=1,
        sample_message="Minor deprecation warning"
    )
    assert p4 == "P4 - Low"
    assert score4 < 45.0
