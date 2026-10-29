"""Log parsing engine.

Reads log files line by line, identifies severity levels (DEBUG, INFO, WARNING, ERROR, CRITICAL),
extracts timestamps and components, preserves exact source line numbers, and safely handles
unstructured or malformed lines without throwing unhandled exceptions.
"""

import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ParsedLogLine:
    """Represents a single parsed line from a log file."""
    line_number: int
    timestamp: Optional[str]
    severity: str  # DEBUG, INFO, WARNING, ERROR, CRITICAL, or UNSTRUCTURED
    message: str
    raw_line: str
    component: Optional[str] = None


class LogParser:
    """Deterministic, regex-assisted log parser for standard server and application logs."""

    # Standardized severity mapping (normalizes WARN -> WARNING, FATAL -> CRITICAL)
    SEVERITY_MAP = {
        "DEBUG": "DEBUG",
        "INFO": "INFO",
        "WARN": "WARNING",
        "WARNING": "WARNING",
        "ERROR": "ERROR",
        "CRIT": "CRITICAL",
        "CRITICAL": "CRITICAL",
        "FATAL": "CRITICAL",
    }

    # Regex patterns for severity detection (word boundaries prevent substring false positives)
    SEVERITY_PATTERN = re.compile(
        r"\b(DEBUG|INFO|WARN(?:ING)?|ERROR|CRIT(?:ICAL)?|FATAL)\b",
        re.IGNORECASE
    )

    # Regex patterns for timestamp extraction
    # 1. ISO-8601: 2026-10-29 14:22:31 or 2026-10-29T14:22:31.456Z
    ISO_TIMESTAMP_PATTERN = re.compile(
        r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?(?:Z|[+-]\d{2}:?\d{2})?)"
    )
    # 2. Bracketed Apache / Common Log: [29/Oct/2026:14:22:31 +0000]
    APACHE_TIMESTAMP_PATTERN = re.compile(
        r"\[(\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2}(?:\s+[+-]\d{4})?)\]"
    )
    # 3. Syslog style: Oct 29 14:22:31
    SYSLOG_TIMESTAMP_PATTERN = re.compile(
        r"\b([A-Za-z]{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\b"
    )

    # Component / Logger pattern: [service-name] or (module_name)
    COMPONENT_PATTERN = re.compile(r"\[([a-zA-Z0-9_\-\.]+)\]|\(([a-zA-Z0-9_\-\.]+)\)")

    def parse_line(self, line: str, line_number: int) -> ParsedLogLine:
        """Parse a single raw log line into a structured ParsedLogLine object.
        
        Args:
            line: The raw text string of the log line.
            line_number: The 1-based index of this line in the source file.
            
        Returns:
            ParsedLogLine dataclass instance.
        """
        raw_line = line.rstrip("\r\n")

        # 1. Extract Timestamp
        timestamp = self._extract_timestamp(raw_line)

        # 2. Extract Severity
        severity = self._extract_severity(raw_line)

        # 3. Extract Component (if bracketed)
        component = self._extract_component(raw_line)

        # 4. Clean Message
        message = self._extract_message(raw_line, timestamp, severity, component)

        return ParsedLogLine(
            line_number=line_number,
            timestamp=timestamp,
            severity=severity,
            message=message,
            raw_line=raw_line,
            component=component
        )

    def parse_text(self, text: str) -> List[ParsedLogLine]:
        """Parse the full text content into a list of ParsedLogLine items.
        
        Args:
            text: Entire content of the log file.
            
        Returns:
            List of ParsedLogLine items preserving line order and numbering.
        """
        parsed_lines: List[ParsedLogLine] = []
        lines = text.splitlines()

        for idx, line in enumerate(lines, start=1):
            # Skip completely empty trailing lines if needed, but preserve line numbering
            parsed = self.parse_line(line, line_number=idx)
            parsed_lines.append(parsed)

        return parsed_lines

    def _extract_timestamp(self, line: str) -> Optional[str]:
        """Attempt to extract timestamp using prioritized patterns."""
        iso_match = self.ISO_TIMESTAMP_PATTERN.search(line)
        if iso_match:
            return iso_match.group(1)

        apache_match = self.APACHE_TIMESTAMP_PATTERN.search(line)
        if apache_match:
            return apache_match.group(1)

        syslog_match = self.SYSLOG_TIMESTAMP_PATTERN.search(line)
        if syslog_match:
            return syslog_match.group(1)

        return None

    def _extract_severity(self, line: str) -> str:
        """Identify severity token. If not found, classify as UNSTRUCTURED."""
        match = self.SEVERITY_PATTERN.search(line)
        if match:
            token = match.group(1).upper()
            return self.SEVERITY_MAP.get(token, "INFO")
        return "UNSTRUCTURED"

    def _extract_component(self, line: str) -> Optional[str]:
        """Extract service name or module identifier if present."""
        match = self.COMPONENT_PATTERN.search(line)
        if match:
            return match.group(1) or match.group(2)
        return None

    def _extract_message(
        self,
        line: str,
        timestamp: Optional[str],
        severity: str,
        component: Optional[str]
    ) -> str:
        """Strip matched prefix metadata to obtain the core message content."""
        msg = line

        # If line is unstructured or just message, return cleaned line
        if severity == "UNSTRUCTURED":
            return msg.strip()

        # Remove timestamp if found
        if timestamp:
            msg = msg.replace(timestamp, "", 1)

        # Remove bracketed component if found
        if component:
            msg = re.sub(rf"\[\s*{re.escape(component)}\s*\]|\(\s*{re.escape(component)}\s*\)", "", msg, count=1)

        # Remove severity keyword if matched at boundary
        msg = re.sub(rf"\b{re.escape(severity)}\b", "", msg, count=1, flags=re.IGNORECASE)

        # Clean remaining punctuation separators like ' - ', ' : ', '[]'
        msg = re.sub(r"^[\s\-\:\[\]\|]+", "", msg)
        cleaned = msg.strip()

        return cleaned if cleaned else line.strip()
