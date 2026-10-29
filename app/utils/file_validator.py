"""File validation and safe reading utilities.

Ensures uploaded files have valid extensions, stay within size limits,
contain safe text data rather than binary executables, and decode cleanly without crashing.
"""

import os
from typing import Tuple
from app.config import get_settings


class FileValidationError(Exception):
    """Custom exception raised when an uploaded log file violates validation rules."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def validate_file_metadata(filename: str, file_size: int) -> None:
    """Validate file extension and size before reading contents.
    
    Args:
        filename: Name of the uploaded file.
        file_size: Size of the file in bytes.
        
    Raises:
        FileValidationError: If the file is missing, empty, oversized, or has an invalid extension.
    """
    settings = get_settings()

    if not filename or not filename.strip():
        raise FileValidationError("No filename provided. Please upload a valid log file.", status_code=400)

    # Sanitize and extract extension
    _, ext = os.path.splitext(filename)
    normalized_ext = ext.lower().strip()

    if normalized_ext not in [e.lower() for e in settings.allowed_extensions]:
        allowed = ", ".join(settings.allowed_extensions)
        raise FileValidationError(
            f"Unsupported file extension '{ext}'. Only {allowed} files are accepted.",
            status_code=400
        )

    if file_size == 0:
        raise FileValidationError("The uploaded file is empty (0 bytes). Please upload a file with log content.", status_code=400)

    if file_size > settings.max_upload_size_bytes:
        max_mb = settings.max_upload_size_bytes / (1024 * 1024)
        raise FileValidationError(
            f"File size exceeds the allowed limit of {max_mb:.1f} MB. Please upload a smaller log excerpt.",
            status_code=413
        )


def read_and_validate_content(raw_bytes: bytes) -> str:
    """Safely decode uploaded raw bytes into text while checking for binary data and empty content.
    
    Args:
        raw_bytes: Raw binary content of the file.
        
    Returns:
        Decoded text string.
        
    Raises:
        FileValidationError: If the content is binary or whitespace-only.
    """
    if not raw_bytes or len(raw_bytes.strip()) == 0:
        raise FileValidationError("The uploaded file contains only empty whitespace or no readable content.", status_code=400)

    # Check for binary content (null bytes often indicate compiled binaries or images)
    sample_size = min(len(raw_bytes), 8192)
    if b"\x00" in raw_bytes[:sample_size]:
        raise FileValidationError(
            "Uploaded file appears to be a binary file, not a plain text log file. Execution rejected.",
            status_code=400
        )

    # Attempt UTF-8 decoding first, then fallback to latin-1 with character replacement
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        # Fallback ensures non-UTF8 international server logs don't trigger 500 crashes
        text = raw_bytes.decode("latin-1", errors="replace")

    if not text.strip():
        raise FileValidationError("The log file contains only empty whitespace.", status_code=400)

    return text
