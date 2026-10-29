"""Unit tests for file upload validation rules (file_validator).

Verifies extension checking, empty file rejection, size limits, binary content detection,
and safe text decoding.
"""

import pytest
from app.utils.file_validator import (
    FileValidationError,
    read_and_validate_content,
    validate_file_metadata,
)


def test_validate_metadata_valid_extensions():
    """Verify standard .log and .txt extensions pass validation."""
    validate_file_metadata("app.log", 1024)
    validate_file_metadata("trace.LOG", 1024)
    validate_file_metadata("server.txt", 1024)
    validate_file_metadata("data.TXT", 1024)


def test_validate_metadata_unsupported_extension():
    """Verify non-log extensions raise FileValidationError with HTTP 400."""
    with pytest.raises(FileValidationError) as exc:
        validate_file_metadata("malware.exe", 1024)
    assert exc.value.status_code == 400
    assert "Unsupported file extension" in exc.value.message


def test_validate_metadata_empty_file():
    """Verify 0-byte file raises FileValidationError with HTTP 400."""
    with pytest.raises(FileValidationError) as exc:
        validate_file_metadata("empty.log", 0)
    assert exc.value.status_code == 400
    assert "empty" in exc.value.message.lower()


def test_validate_metadata_oversized_file():
    """Verify file exceeding 5MB raises FileValidationError with HTTP 413."""
    oversized = 6 * 1024 * 1024  # 6 MB
    with pytest.raises(FileValidationError) as exc:
        validate_file_metadata("huge.log", oversized)
    assert exc.value.status_code == 413
    assert "exceeds" in exc.value.message.lower()


def test_read_and_validate_content_rejects_binary():
    """Verify that binary content containing null bytes is rejected."""
    binary_bytes = b"GIF89a\x00\x00\x01\x00\x80\x00\x00"
    with pytest.raises(FileValidationError) as exc:
        read_and_validate_content(binary_bytes)
    assert exc.value.status_code == 400
    assert "binary file" in exc.value.message.lower()


def test_read_and_validate_content_rejects_whitespace_only():
    """Verify that whitespace-only file is rejected."""
    with pytest.raises(FileValidationError) as exc:
        read_and_validate_content(b"   \n\t   \n  ")
    assert exc.value.status_code == 400
    assert "whitespace" in exc.value.message.lower()


def test_read_and_validate_content_safe_decoding():
    """Verify valid UTF-8 and non-standard characters decode safely without crashing."""
    valid_content = "2026-10-29 10:00:00 [INFO] System running cleanly 🚀".encode("utf-8")
    text = read_and_validate_content(valid_content)
    assert "System running cleanly 🚀" in text
