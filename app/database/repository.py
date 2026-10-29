"""Repository pattern implementation for SQLite database operations.

Provides type-safe, parameterized CRUD queries, avoiding SQL injection and managing
transactions cleanly across tables.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from app.database.connection import get_db_connection
from app.services.analyzer import AnalysisResult, ErrorGroup
from app.utils.logger import get_logger

logger = get_logger(__name__)


class AnalysisRepository:
    """Handles persistence and retrieval of log analyses, error groups, and AI diagnoses."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def save_analysis(
        self,
        analysis_id: str,
        filename: str,
        result: AnalysisResult,
        execution_time_ms: float
    ) -> Dict[str, Any]:
        """Atomically persist analysis metadata and its error groups in a single transaction.
        
        Args:
            analysis_id: Unique identifier (e.g. ana_uuid).
            filename: Original sanitized filename.
            result: AnalysisResult instance containing counts and error groups.
            execution_time_ms: Measured parsing and analysis duration.
            
        Returns:
            Dictionary representing the persisted analysis summary.
        """
        uploaded_at = datetime.now(timezone.utc).isoformat()

        insert_analysis_sql = """
        INSERT INTO analyses (
            id, filename, uploaded_at, total_lines, debug_count,
            info_count, warning_count, error_count, critical_count,
            unstructured_count, status, execution_time_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """

        insert_group_sql = """
        INSERT INTO error_groups (
            analysis_id, fingerprint, severity, priority, score,
            count, sample_message, first_line, last_line,
            line_numbers_json, scoring_explanation
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """

        with get_db_connection(self.db_path) as conn:
            # 1. Insert master analysis record
            conn.execute(
                insert_analysis_sql,
                (
                    analysis_id,
                    filename,
                    uploaded_at,
                    result.total_lines,
                    result.debug_count,
                    result.info_count,
                    result.warning_count,
                    result.error_count,
                    result.critical_count,
                    result.unstructured_count,
                    "COMPLETED",
                    execution_time_ms
                )
            )

            # 2. Batch insert associated error groups
            group_rows = []
            for g in result.error_groups:
                group_rows.append((
                    analysis_id,
                    g.fingerprint,
                    g.severity,
                    g.priority,
                    g.score,
                    g.count,
                    g.sample_message,
                    g.first_line,
                    g.last_line,
                    json.dumps(g.line_numbers),
                    g.scoring_explanation
                ))

            if group_rows:
                conn.executemany(insert_group_sql, group_rows)

        logger.info(f"Successfully saved analysis {analysis_id} with {len(result.error_groups)} error groups.")
        return {
            "id": analysis_id,
            "filename": filename,
            "uploaded_at": uploaded_at,
            "total_lines": result.total_lines,
            "debug_count": result.debug_count,
            "info_count": result.info_count,
            "warning_count": result.warning_count,
            "error_count": result.error_count,
            "critical_count": result.critical_count,
            "unstructured_count": result.unstructured_count,
            "status": "COMPLETED",
            "execution_time_ms": execution_time_ms
        }

    def get_analyses(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Retrieve a paginated list of past analyses ordered by upload timestamp descending."""
        sql = """
        SELECT id, filename, uploaded_at, total_lines, debug_count,
               info_count, warning_count, error_count, critical_count,
               unstructured_count, status, execution_time_ms
        FROM analyses
        ORDER BY uploaded_at DESC
        LIMIT ? OFFSET ?;
        """
        with get_db_connection(self.db_path) as conn:
            cursor = conn.execute(sql, (limit, offset))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_analysis_by_id(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single analysis record by its primary key ID."""
        sql = """
        SELECT id, filename, uploaded_at, total_lines, debug_count,
               info_count, warning_count, error_count, critical_count,
               unstructured_count, status, execution_time_ms
        FROM analyses
        WHERE id = ?;
        """
        with get_db_connection(self.db_path) as conn:
            cursor = conn.execute(sql, (analysis_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_error_groups(
        self,
        analysis_id: str,
        severity_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve all error groups belonging to a specific analysis, optionally filtered by severity."""
        if severity_filter:
            sql = """
            SELECT id, analysis_id, fingerprint, severity, priority, score,
                   count, sample_message, first_line, last_line,
                   line_numbers_json, scoring_explanation
            FROM error_groups
            WHERE analysis_id = ? AND UPPER(severity) = UPPER(?)
            ORDER BY score DESC, count DESC;
            """
            params = (analysis_id, severity_filter)
        else:
            sql = """
            SELECT id, analysis_id, fingerprint, severity, priority, score,
                   count, sample_message, first_line, last_line,
                   line_numbers_json, scoring_explanation
            FROM error_groups
            WHERE analysis_id = ?
            ORDER BY score DESC, count DESC;
            """
            params = (analysis_id,)

        with get_db_connection(self.db_path) as conn:
            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()
            results = []
            for row in rows:
                item = dict(row)
                try:
                    item["line_numbers"] = json.loads(item["line_numbers_json"])
                except Exception:
                    item["line_numbers"] = []
                results.append(item)
            return results

    def get_error_group_by_id(self, error_group_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a specific error group record by its integer ID."""
        sql = """
        SELECT id, analysis_id, fingerprint, severity, priority, score,
               count, sample_message, first_line, last_line,
               line_numbers_json, scoring_explanation
        FROM error_groups
        WHERE id = ?;
        """
        with get_db_connection(self.db_path) as conn:
            cursor = conn.execute(sql, (error_group_id,))
            row = cursor.fetchone()
            if not row:
                return None
            item = dict(row)
            try:
                item["line_numbers"] = json.loads(item["line_numbers_json"])
            except Exception:
                item["line_numbers"] = []
            return item

    def save_ai_diagnosis(
        self,
        analysis_id: str,
        error_group_id: Optional[int],
        probable_cause: str,
        supporting_evidence: List[str],
        debugging_steps: List[str],
        confidence: str,
        limitations: str,
        model_used: str
    ) -> Dict[str, Any]:
        """Save a validated AI or heuristic diagnosis for an incident."""
        created_at = datetime.now(timezone.utc).isoformat()
        sql = """
        INSERT INTO ai_diagnoses (
            analysis_id, error_group_id, probable_cause,
            supporting_evidence_json, debugging_steps_json,
            confidence, limitations, model_used, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        with get_db_connection(self.db_path) as conn:
            cursor = conn.execute(
                sql,
                (
                    analysis_id,
                    error_group_id,
                    probable_cause,
                    json.dumps(supporting_evidence),
                    json.dumps(debugging_steps),
                    confidence,
                    limitations,
                    model_used,
                    created_at
                )
            )
            diag_id = cursor.lastrowid

        return {
            "id": diag_id,
            "analysis_id": analysis_id,
            "error_group_id": error_group_id,
            "probable_cause": probable_cause,
            "supporting_evidence": supporting_evidence,
            "debugging_steps": debugging_steps,
            "confidence": confidence,
            "limitations": limitations,
            "model_used": model_used,
            "created_at": created_at
        }

    def get_ai_diagnoses_by_analysis(self, analysis_id: str) -> List[Dict[str, Any]]:
        """Retrieve all diagnoses recorded for a specific analysis."""
        sql = """
        SELECT id, analysis_id, error_group_id, probable_cause,
               supporting_evidence_json, debugging_steps_json,
               confidence, limitations, model_used, created_at
        FROM ai_diagnoses
        WHERE analysis_id = ?
        ORDER BY created_at DESC;
        """
        with get_db_connection(self.db_path) as conn:
            cursor = conn.execute(sql, (analysis_id,))
            rows = cursor.fetchall()
            results = []
            for row in rows:
                item = dict(row)
                try:
                    item["supporting_evidence"] = json.loads(item["supporting_evidence_json"])
                except Exception:
                    item["supporting_evidence"] = []
                try:
                    item["debugging_steps"] = json.loads(item["debugging_steps_json"])
                except Exception:
                    item["debugging_steps"] = []
                results.append(item)
            return results
