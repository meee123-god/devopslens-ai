"""HTTP client communicating with the DevOpsLens AI FastAPI backend.

Wraps backend REST endpoints with safe timeouts, structured exception handling,
and clean response mappings for the Streamlit dashboard.
"""

import os
from typing import Any, Dict, List, Optional
import requests


class BackendAPIClient:
    """Client for communicating with the DevOpsLens FastAPI REST API."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or os.getenv("API_BASE_URL", "http://127.0.0.1:8000")).rstrip("/")
        self.timeout = 15.0  # seconds

    def check_health(self) -> Dict[str, Any]:
        """Check status of backend API and database."""
        try:
            resp = requests.get(f"{self.base_url}/health", timeout=self.timeout)
            if resp.status_code == 200:
                return resp.json()
            return {"status": "degraded", "database_connected": False, "ai_enabled": False}
        except Exception:
            return {"status": "offline", "database_connected": False, "ai_enabled": False}

    def analyze_log(self, filename: str, file_bytes: bytes) -> Dict[str, Any]:
        """Upload log file to /analyze endpoint."""
        url = f"{self.base_url}/analyze"
        files = {"file": (filename, file_bytes, "text/plain")}
        resp = requests.post(url, files=files, timeout=self.timeout)

        if resp.status_code == 201:
            return resp.json()

        try:
            err_data = resp.json()
            msg = err_data.get("detail", f"Server returned error code {resp.status_code}")
        except Exception:
            msg = f"HTTP {resp.status_code}: {resp.text}"

        raise RuntimeError(msg)

    def get_analyses(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Retrieve recent analysis history."""
        try:
            url = f"{self.base_url}/analyses?limit={limit}&offset={offset}"
            resp = requests.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                return resp.json()
            return []
        except Exception:
            return []

    def get_analysis_details(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve full details of an analysis by ID."""
        try:
            url = f"{self.base_url}/analyses/{analysis_id}"
            resp = requests.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception:
            return None

    def request_diagnosis(self, analysis_id: str, error_group_id: int) -> Dict[str, Any]:
        """Request AI / heuristic diagnosis for a specific error group."""
        url = f"{self.base_url}/analyze/diagnose"
        payload = {"analysis_id": analysis_id, "error_group_id": error_group_id}
        resp = requests.post(url, json=payload, timeout=self.timeout)

        if resp.status_code == 200:
            return resp.json()

        try:
            err = resp.json().get("detail", "Diagnosis failed.")
        except Exception:
            err = resp.text
        raise RuntimeError(err)

    def export_report(self, analysis_id: str, format_type: str = "json") -> str:
        """Export report in json or csv format."""
        url = f"{self.base_url}/analyses/{analysis_id}/export?format={format_type}"
        resp = requests.get(url, timeout=self.timeout)
        if resp.status_code == 200:
            return resp.text
        raise RuntimeError(f"Failed to export report: {resp.text}")
