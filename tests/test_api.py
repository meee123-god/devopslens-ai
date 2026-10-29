"""Integration tests for FastAPI REST API endpoints.

Verifies HTTP methods, status codes, input validation guards, response schemas,
and error handling.
"""

import io


def test_health_endpoint(client):
    """Verify GET /health returns 200 OK with system status."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("healthy", "degraded")
    assert "version" in data
    assert "database_connected" in data


def test_analyze_valid_log_file(client, sample_log_text):
    """Verify POST /analyze returns 201 Created with summary and error groups."""
    file_bytes = sample_log_text.encode("utf-8")
    files = {"file": ("app.log", io.BytesIO(file_bytes), "text/plain")}

    resp = client.post("/analyze", files=files)
    assert resp.status_code == 201
    data = resp.json()

    assert "summary" in data
    assert "error_groups" in data
    summary = data["summary"]
    assert summary["filename"] == "app.log"
    assert summary["error_count"] >= 2
    assert summary["critical_count"] >= 1
    assert len(data["error_groups"]) >= 2


def test_analyze_empty_file_returns_400(client):
    """Verify POST /analyze rejects empty files with 400 Bad Request."""
    files = {"file": ("empty.log", io.BytesIO(b""), "text/plain")}
    resp = client.post("/analyze", files=files)
    assert resp.status_code == 400
    assert "empty" in resp.json()["detail"].lower()


def test_analyze_unsupported_extension_returns_400(client):
    """Verify POST /analyze rejects disallowed extensions with 400 Bad Request."""
    files = {"file": ("script.sh", io.BytesIO(b"echo hello"), "text/plain")}
    resp = client.post("/analyze", files=files)
    assert resp.status_code == 400
    assert "Unsupported file extension" in resp.json()["detail"]


def test_get_analyses_and_details(client, sample_log_text):
    """Verify GET /analyses lists history and GET /analyses/{id} retrieves details."""
    # 1. Upload a log first
    files = {"file": ("trace.log", io.BytesIO(sample_log_text.encode("utf-8")), "text/plain")}
    create_resp = client.post("/analyze", files=files)
    assert create_resp.status_code == 201
    analysis_id = create_resp.json()["summary"]["id"]

    # 2. List analyses
    list_resp = client.get("/analyses")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert any(a["id"] == analysis_id for a in items)

    # 3. Retrieve specific analysis
    get_resp = client.get(f"/analyses/{analysis_id}")
    assert get_resp.status_code == 200
    detail = get_resp.json()
    assert detail["summary"]["id"] == analysis_id
    assert len(detail["error_groups"]) > 0


def test_get_analysis_not_found(client):
    """Verify GET /analyses/non_existent returns 404 Not Found."""
    resp = client.get("/analyses/ana_does_not_exist_999")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_get_analysis_errors_with_filter(client, sample_log_text):
    """Verify GET /analyses/{id}/errors retrieves error groups and supports severity filtering."""
    files = {"file": ("filter.log", io.BytesIO(sample_log_text.encode("utf-8")), "text/plain")}
    create_resp = client.post("/analyze", files=files)
    analysis_id = create_resp.json()["summary"]["id"]

    # Filter by CRITICAL
    crit_resp = client.get(f"/analyses/{analysis_id}/errors?severity=CRITICAL")
    assert crit_resp.status_code == 200
    crit_groups = crit_resp.json()
    assert len(crit_groups) >= 1
    assert all(g["severity"] == "CRITICAL" for g in crit_groups)


def test_diagnose_endpoint(client, sample_log_text):
    """Verify POST /analyze/diagnose runs grounded diagnosis on an error group."""
    files = {"file": ("diag.log", io.BytesIO(sample_log_text.encode("utf-8")), "text/plain")}
    create_resp = client.post("/analyze", files=files)
    analysis_id = create_resp.json()["summary"]["id"]
    error_group_id = create_resp.json()["error_groups"][0]["id"]

    payload = {"analysis_id": analysis_id, "error_group_id": error_group_id}
    diag_resp = client.post("/analyze/diagnose", json=payload)
    assert diag_resp.status_code == 200
    diag = diag_resp.json()
    assert "probable_cause" in diag
    assert "supporting_evidence" in diag
    assert "debugging_steps" in diag
    assert "confidence" in diag
    assert "limitations" in diag


def test_export_analysis_json_and_csv(client, sample_log_text):
    """Verify GET /analyses/{id}/export supports JSON and CSV exports."""
    files = {"file": ("export.log", io.BytesIO(sample_log_text.encode("utf-8")), "text/plain")}
    create_resp = client.post("/analyze", files=files)
    analysis_id = create_resp.json()["summary"]["id"]

    # Export JSON
    json_resp = client.get(f"/analyses/{analysis_id}/export?format=json")
    assert json_resp.status_code == 200
    assert "summary" in json_resp.json()

    # Export CSV
    csv_resp = client.get(f"/analyses/{analysis_id}/export?format=csv")
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    assert "Error ID,Severity,Priority" in csv_resp.text
