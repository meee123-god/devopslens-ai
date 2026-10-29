"""Deterministic log analysis, error grouping, and rule-based priority ranking.

Groups recurring errors by normalized message fingerprints and ranks issues using
transparent, fully explainable mathematical scoring rules (not black-box ML).
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from app.services.parser import ParsedLogLine


@dataclass
class ErrorGroup:
    """Group of identical or recurring error occurrences."""
    fingerprint: str
    severity: str
    count: int
    priority: str
    score: float
    sample_message: str
    first_line: int
    last_line: int
    line_numbers: List[int] = field(default_factory=list)
    scoring_explanation: str = ""


@dataclass
class AnalysisResult:
    """Aggregated analysis report for an entire log file."""
    total_lines: int
    debug_count: int
    info_count: int
    warning_count: int
    error_count: int
    critical_count: int
    unstructured_count: int
    error_groups: List[ErrorGroup]
    lines: List[ParsedLogLine]


class LogAnalyzer:
    """Performs deterministic aggregation, fingerprinting, and transparent priority ranking."""

    # Base severity score weights
    SEVERITY_WEIGHTS = {
        "CRITICAL": 100.0,
        "ERROR": 60.0,
        "WARNING": 30.0,
        "UNSTRUCTURED": 10.0,
        "INFO": 5.0,
        "DEBUG": 1.0,
    }

    # Architectural impact keywords indicating severe system failure
    CRITICAL_KEYWORDS = [
        "database", "connection refused", "deadlock", "timeout",
        "out of memory", "oom", "disk full", "unauthorized",
        "segmentation fault", "nullpointer", "panic", "fatal", "crash"
    ]

    # Regex normalization patterns for dynamic tokens
    HEX_PATTERN = re.compile(r"\b0x[0-9a-fA-F]+\b")
    UUID_PATTERN = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
    IP_PATTERN = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d+)?\b")
    NUM_PATTERN = re.compile(r"\b\d+\b")
    QUOTED_PATTERN = re.compile(r"['\"][^'\"]*['\"]")

    def generate_fingerprint(self, message: str) -> str:
        """Create a normalized signature by replacing dynamic IDs, addresses, and numbers.
        
        Example:
            'Connection to 192.168.1.10:5432 failed after 30s'
            -> 'Connection to <IP> failed after <NUM>s'
        """
        normalized = message.strip()
        normalized = self.UUID_PATTERN.sub("<UUID>", normalized)
        normalized = self.HEX_PATTERN.sub("<HEX>", normalized)
        normalized = self.IP_PATTERN.sub("<IP>", normalized)
        normalized = self.QUOTED_PATTERN.sub("<STR>", normalized)
        normalized = self.NUM_PATTERN.sub("<NUM>", normalized)
        # Collapse multiple spaces
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized if normalized else "Empty or whitespace message"

    def calculate_priority(self, severity: str, count: int, sample_message: str) -> Tuple[str, float, str]:
        """Calculate a transparent priority ranking and score.
        
        Rules:
        - Base Severity: CRITICAL = 100, ERROR = 60, WARNING = 30, others = 10
        - Frequency Factor: min(count * 3, 40) points
        - Critical Keyword Boost: +15 points if message mentions DB/network/memory failure
        
        Priority tiers:
        - Score >= 110: P1 - Critical
        - Score >= 80:  P2 - High
        - Score >= 45:  P3 - Medium
        - Score < 45:   P4 - Low
        
        Returns:
            Tuple of (priority_label, total_score, explanation_text)
        """
        base_score = self.SEVERITY_WEIGHTS.get(severity.upper(), 10.0)
        freq_boost = min(count * 3.0, 40.0)

        # Keyword matching
        lower_msg = sample_message.lower()
        matched_keywords = [kw for kw in self.CRITICAL_KEYWORDS if kw in lower_msg]
        keyword_boost = 15.0 if matched_keywords else 0.0

        total_score = base_score + freq_boost + keyword_boost

        if total_score >= 110.0:
            priority = "P1 - Critical"
        elif total_score >= 80.0:
            priority = "P2 - High"
        elif total_score >= 45.0:
            priority = "P3 - Medium"
        else:
            priority = "P4 - Low"

        explanation_parts = [f"Base severity ({severity}={base_score:.0f})"]
        if freq_boost > 0:
            explanation_parts.append(f"Frequency boost (+{freq_boost:.0f} pts for {count} occurrences)")
        if keyword_boost > 0:
            kw_str = ", ".join(f"'{k}'" for k in matched_keywords[:2])
            explanation_parts.append(f"Critical keyword boost (+{keyword_boost:.0f} pts for {kw_str})")

        explanation = " + ".join(explanation_parts) + f" = {total_score:.1f}"

        return priority, total_score, explanation

    def analyze(self, parsed_lines: List[ParsedLogLine]) -> AnalysisResult:
        """Aggregate parsed lines, count severities, group errors, and rank issues.
        
        Args:
            parsed_lines: List of ParsedLogLine objects from LogParser.
            
        Returns:
            AnalysisResult containing overall counts and ranked error groups.
        """
        debug_count = 0
        info_count = 0
        warning_count = 0
        error_count = 0
        critical_count = 0
        unstructured_count = 0

        # Mapping: fingerprint -> dictionary of collected occurrences
        groups_dict: Dict[str, Dict] = {}

        for line in parsed_lines:
            sev = line.severity.upper()
            if sev == "DEBUG":
                debug_count += 1
            elif sev == "INFO":
                info_count += 1
            elif sev == "WARNING":
                warning_count += 1
            elif sev == "ERROR":
                error_count += 1
            elif sev == "CRITICAL":
                critical_count += 1
            else:
                unstructured_count += 1

            # Group errors, critical events, and warnings into triage groups
            if sev in ("ERROR", "CRITICAL", "WARNING"):
                fp = self.generate_fingerprint(line.message)

                if fp not in groups_dict:
                    groups_dict[fp] = {
                        "fingerprint": fp,
                        "severity": sev,
                        "sample_message": line.message,
                        "first_line": line.line_number,
                        "last_line": line.line_number,
                        "line_numbers": [line.line_number],
                        "count": 1
                    }
                else:
                    entry = groups_dict[fp]
                    entry["count"] += 1
                    entry["last_line"] = line.line_number
                    entry["line_numbers"].append(line.line_number)
                    # Escalate group severity if a CRITICAL event shares fingerprint with WARNING/ERROR
                    if sev == "CRITICAL":
                        entry["severity"] = "CRITICAL"

        # Calculate ranking and instantiate ErrorGroup objects
        error_groups: List[ErrorGroup] = []
        for fp, data in groups_dict.items():
            priority, score, explanation = self.calculate_priority(
                severity=data["severity"],
                count=data["count"],
                sample_message=data["sample_message"]
            )
            error_groups.append(
                ErrorGroup(
                    fingerprint=data["fingerprint"],
                    severity=data["severity"],
                    count=data["count"],
                    priority=priority,
                    score=score,
                    sample_message=data["sample_message"],
                    first_line=data["first_line"],
                    last_line=data["last_line"],
                    line_numbers=data["line_numbers"],
                    scoring_explanation=explanation
                )
            )

        # Sort error groups by score descending (highest priority first), then by count descending
        error_groups.sort(key=lambda g: (g.score, g.count), reverse=True)

        return AnalysisResult(
            total_lines=len(parsed_lines),
            debug_count=debug_count,
            info_count=info_count,
            warning_count=warning_count,
            error_count=error_count,
            critical_count=critical_count,
            unstructured_count=unstructured_count,
            error_groups=error_groups,
            lines=parsed_lines
        )
