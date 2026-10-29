"""FastAPI route handlers for DevOpsLens AI.

Implements RESTful endpoints with input validation, Pydantic response models,
and consistent error handling.
"""

import csv
import io
import time
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response

from app.api.schemas import (
    AnalysisDetailResponse,
    AnalysisSummaryResponse,
    DiagnoseRequest,
    ErrorGroupResponse,
    HealthResponse,
)
from app.ai.client import AIDiagnosisClient
from app.ai.validator import DiagnosisResponse
from app.config import Settings, get_settings
from app.database.connection import get_db_connection
from app.database.repository import AnalysisRepository
from app.services.analyzer import LogAnalyzer
from app.services.parser import LogParser
from app.utils.file_validator import (
    FileValidationError,
    read_and_validate_content,
    validate_file_metadata,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


def get_repository() -> AnalysisRepository:
    """Dependency provider for the database repository."""
    return AnalysisRepository()


def get_ai_client() -> AIDiagnosisClient:
    """Dependency provider for the AI diagnosis client."""
    return AIDiagnosisClient()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    tags=["System"]
)
def check_health(settings: Settings = Depends(get_settings)):
    """Report application health, version, AI status, and database connectivity."""
    db_connected = False
    try:
        with get_db_connection() as conn:
            cursor = conn.execute("SELECT 1;")
            if cursor.fetchone()[0] == 1:
                db_connected = True
    except Exception as exc:
        logger.error(f"Health check database ping failed: {exc}")
        db_connected = False

    return HealthResponse(
        status="healthy" if db_connected else "degraded",
        version=settings.app_version,
        environment=settings.environment,
        ai_enabled=settings.is_ai_enabled,
        ai_provider=settings.ai_provider,
        database_connected=db_connected
    )


@router.post(
    "/analyze",
    response_model=AnalysisDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and analyze a log file",
    tags=["Analysis"]
)
async def analyze_log(
    file: UploadFile = File(..., description="Application log file (.log or .txt)"),
    repo: AnalysisRepository = Depends(get_repository)
):
    """Parse, aggregate, and rank issues from an uploaded log file, persisting the result to SQLite."""
    start_time = time.perf_counter()

    # 1. Read raw file bytes safely
    try:
        raw_bytes = await file.read()
    except Exception as exc:
        logger.error(f"Failed reading uploaded file: {exc}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to read the uploaded file stream."
        )

    # 2. Validate metadata & text content
    try:
        validate_file_metadata(file.filename or "", len(raw_bytes))
        content = read_and_validate_content(raw_bytes)
    except FileValidationError as err:
        logger.warning(f"File validation rejected upload '{file.filename}': {err.message}")
        raise HTTPException(status_code=err.status_code, detail=err.message)

    # 3. Parse log lines
    parser = LogParser()
    parsed_lines = parser.parse_text(content)

    # 4. Deterministic analysis and transparent priority ranking
    analyzer = LogAnalyzer()
    analysis_result = analyzer.analyze(parsed_lines)

    execution_duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    analysis_id = f"ana_{uuid.uuid4().hex[:12]}"

    # 5. Persist to SQLite
    try:
        saved_summary = repo.save_analysis(
            analysis_id=analysis_id,
            filename=file.filename or "unknown.log",
            result=analysis_result,
            execution_time_ms=execution_duration_ms
        )
    except Exception as exc:
        logger.error(f"Failed to persist analysis to database: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database write failed while saving analysis results."
        )

    # 6. Retrieve persisted error groups with database IDs
    stored_groups = repo.get_error_groups(analysis_id)

    return AnalysisDetailResponse(
        summary=AnalysisSummaryResponse(**saved_summary),
        error_groups=[ErrorGroupResponse(**g) for g in stored_groups]
    )


@router.post(
    "/analyze/diagnose",
    response_model=DiagnosisResponse,
    summary="Generate AI/heuristic diagnosis for a specific error group",
    tags=["Analysis"]
)
def diagnose_error(
    request: DiagnoseRequest,
    repo: AnalysisRepository = Depends(get_repository),
    ai_client: AIDiagnosisClient = Depends(get_ai_client)
):
    """Diagnose an error group using AI or expert heuristics, verifying evidence against log lines."""
    # 1. Verify parent analysis exists
    analysis = repo.get_analysis_by_id(request.analysis_id)
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis with ID '{request.analysis_id}' was not found."
        )

    # 2. Verify error group exists
    error_group = repo.get_error_group_by_id(request.error_group_id)
    if not error_group or error_group["analysis_id"] != request.analysis_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Error group with ID '{request.error_group_id}' was not found in this analysis."
        )

    # 3. Context lines (sample message and nearby line representations)
    context_lines = [
        f"Line {error_group['first_line']}: {error_group['sample_message']}"
    ]
    if error_group['count'] > 1:
        context_lines.append(
            f"Line {error_group['last_line']}: {error_group['sample_message']} (Recurring {error_group['count']} times)"
        )

    # 4. Generate diagnosis
    diagnosis = ai_client.diagnose_issue(
        error_message=error_group["sample_message"],
        severity=error_group["severity"],
        occurrence_count=error_group["count"],
        surrounding_lines=context_lines
    )

    # 5. Persist diagnosis in database
    try:
        repo.save_ai_diagnosis(
            analysis_id=request.analysis_id,
            error_group_id=request.error_group_id,
            probable_cause=diagnosis.probable_cause,
            supporting_evidence=diagnosis.supporting_evidence,
            debugging_steps=diagnosis.debugging_steps,
            confidence=diagnosis.confidence,
            limitations=diagnosis.limitations,
            model_used=diagnosis.model_used
        )
    except Exception as exc:
        logger.warning(f"Could not persist AI diagnosis to database: {exc}")

    return diagnosis


@router.get(
    "/analyses",
    response_model=List[AnalysisSummaryResponse],
    summary="List past analyses",
    tags=["Analysis"]
)
def list_analyses(
    limit: int = Query(default=20, ge=1, le=100, description="Max records to return"),
    offset: int = Query(default=0, ge=0, description="Records to skip"),
    repo: AnalysisRepository = Depends(get_repository)
):
    """Retrieve a paginated history of past log analyses."""
    analyses = repo.get_analyses(limit=limit, offset=offset)
    return [AnalysisSummaryResponse(**a) for a in analyses]


@router.get(
    "/analyses/{analysis_id}",
    response_model=AnalysisDetailResponse,
    summary="Get analysis details by ID",
    tags=["Analysis"]
)
def get_analysis(
    analysis_id: str,
    repo: AnalysisRepository = Depends(get_repository)
):
    """Retrieve full analysis summary and its ranked error groups."""
    summary = repo.get_analysis_by_id(analysis_id)
    if not summary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis with ID '{analysis_id}' was not found."
        )

    error_groups = repo.get_error_groups(analysis_id)
    return AnalysisDetailResponse(
        summary=AnalysisSummaryResponse(**summary),
        error_groups=[ErrorGroupResponse(**g) for g in error_groups]
    )


@router.get(
    "/analyses/{analysis_id}/errors",
    response_model=List[ErrorGroupResponse],
    summary="Get error groups for an analysis",
    tags=["Analysis"]
)
def get_analysis_errors(
    analysis_id: str,
    severity: Optional[str] = Query(default=None, description="Filter by severity: ERROR, CRITICAL, WARNING"),
    repo: AnalysisRepository = Depends(get_repository)
):
    """Retrieve error groups for an analysis, optionally filtered by severity level."""
    # Ensure analysis exists
    summary = repo.get_analysis_by_id(analysis_id)
    if not summary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis with ID '{analysis_id}' was not found."
        )

    error_groups = repo.get_error_groups(analysis_id, severity_filter=severity)
    return [ErrorGroupResponse(**g) for g in error_groups]


@router.get(
    "/analyses/{analysis_id}/export",
    summary="Export analysis as JSON or CSV",
    tags=["Analysis"]
)
def export_analysis(
    analysis_id: str,
    format: str = Query(default="json", pattern="^(json|csv)$", description="Export format: json or csv"),
    repo: AnalysisRepository = Depends(get_repository)
):
    """Export analysis data in JSON or CSV format."""
    summary = repo.get_analysis_by_id(analysis_id)
    if not summary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis with ID '{analysis_id}' was not found."
        )

    error_groups = repo.get_error_groups(analysis_id)

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        # Write CSV header
        writer.writerow([
            "Error ID", "Severity", "Priority", "Score", "Occurrences",
            "First Line", "Last Line", "Sample Message", "Scoring Explanation"
        ])
        for g in error_groups:
            writer.writerow([
                g.get("id"),
                g.get("severity"),
                g.get("priority"),
                g.get("score"),
                g.get("count"),
                g.get("first_line"),
                g.get("last_line"),
                g.get("sample_message"),
                g.get("scoring_explanation")
            ])
        csv_content = output.getvalue()
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={analysis_id}_report.csv"}
        )

    # JSON export
    return {
        "summary": summary,
        "error_groups": error_groups
    }
