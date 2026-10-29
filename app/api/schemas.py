"""Pydantic schemas for request validation and OpenAPI response documentation."""

from typing import List, Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health check response schema."""
    status: str = Field(examples=["healthy"])
    version: str = Field(examples=["1.0.0"])
    environment: str = Field(examples=["development"])
    ai_enabled: bool = Field(examples=[False])
    ai_provider: str = Field(examples=["offline"])
    database_connected: bool = Field(examples=[True])


class ErrorGroupResponse(BaseModel):
    """Schema for a grouped error and its priority ranking."""
    id: Optional[int] = Field(default=None, description="Database row ID if persisted")
    analysis_id: Optional[str] = Field(default=None, description="Associated analysis UUID")
    fingerprint: str = Field(description="Normalized message signature")
    severity: str = Field(description="Severity tier: CRITICAL, ERROR, WARNING")
    priority: str = Field(description="Transparent triage priority: P1, P2, P3, P4")
    score: float = Field(description="Calculated triage score")
    count: int = Field(description="Number of times this error occurred")
    sample_message: str = Field(description="Representative log message")
    first_line: int = Field(description="First line number where this issue occurred")
    last_line: int = Field(description="Last line number where this issue occurred")
    line_numbers: List[int] = Field(description="All line numbers where this error was observed")
    scoring_explanation: str = Field(description="Transparent explanation of how priority score was computed")


class AnalysisSummaryResponse(BaseModel):
    """High-level summary statistics of a log analysis."""
    id: str = Field(description="Unique analysis UUID")
    filename: str = Field(description="Original uploaded log filename")
    uploaded_at: str = Field(description="ISO-8601 UTC timestamp of the upload")
    total_lines: int = Field(description="Total lines parsed")
    debug_count: int = Field(description="Count of DEBUG lines")
    info_count: int = Field(description="Count of INFO lines")
    warning_count: int = Field(description="Count of WARNING lines")
    error_count: int = Field(description="Count of ERROR lines")
    critical_count: int = Field(description="Count of CRITICAL lines")
    unstructured_count: int = Field(description="Count of UNSTRUCTURED lines")
    status: str = Field(default="COMPLETED", description="Analysis execution status")
    execution_time_ms: float = Field(description="Duration of parsing and analysis in milliseconds")


class AnalysisDetailResponse(BaseModel):
    """Complete analysis response containing summary metrics and ranked error groups."""
    summary: AnalysisSummaryResponse
    error_groups: List[ErrorGroupResponse]


class DiagnoseRequest(BaseModel):
    """Request payload to trigger AI/heuristic diagnosis for a specific error group."""
    analysis_id: str = Field(description="UUID of the parent analysis")
    error_group_id: int = Field(description="Integer ID of the error group to triage")


class ErrorResponse(BaseModel):
    """Standardized API error response schema."""
    error: str = Field(description="Brief error category")
    detail: str = Field(description="Detailed safe error message")
    status_code: int = Field(description="HTTP status code")
