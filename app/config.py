"""Application configuration settings for DevOpsLens AI.

Uses Pydantic BaseSettings to read settings from environment variables or a .env file.
Values are typed, validated at startup, and accessible across the entire application.
"""

from functools import lru_cache
from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for DevOpsLens AI."""

    # Application metadata
    app_name: str = Field(default="DevOpsLens AI", description="Display name of the application")
    app_version: str = Field(default="1.0.0", description="Application semantic version")
    environment: str = Field(default="development", description="Runtime environment (development, testing, production)")
    debug: bool = Field(default=False, description="Debug mode flag")

    # Network / Server
    host: str = Field(default="127.0.0.1", description="FastAPI server host")
    port: int = Field(default=8000, description="FastAPI server port")

    # File Upload Restrictions (Safety boundaries)
    max_upload_size_bytes: int = Field(
        default=5 * 1024 * 1024,  # 5 MB
        description="Maximum allowed file size in bytes for uploaded logs"
    )
    allowed_extensions: List[str] = Field(
        default=[".log", ".txt"],
        description="Allowed file extensions for log parsing"
    )

    # SQLite Database Configuration
    database_path: str = Field(
        default="devopslens.db",
        description="Path to the local SQLite database file"
    )

    # AI Configuration (Optional External Integration)
    ai_provider: str = Field(
        default="offline",
        description="AI triage provider: 'offline' (heuristic rule engine), 'gemini', or 'openai'"
    )
    ai_api_key: Optional[str] = Field(
        default=None,
        description="Optional API key for external LLM provider. When empty, offline heuristics are used."
    )
    ai_model_name: str = Field(
        default="gemini-1.5-flash",
        description="Model name to request when calling an external provider"
    )
    ai_request_timeout_seconds: float = Field(
        default=10.0,
        description="Timeout in seconds for external AI network calls to prevent hanging"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def is_ai_enabled(self) -> bool:
        """Return True if an external AI provider and API key are configured."""
        return bool(self.ai_api_key and self.ai_provider.lower() != "offline")


@lru_cache()
def get_settings() -> Settings:
    """Return a cached singleton instance of application settings.
    
    Using @lru_cache prevents re-reading environment variables or parsing the .env file on every call.
    """
    return Settings()
