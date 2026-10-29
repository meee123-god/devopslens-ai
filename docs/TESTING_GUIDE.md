# DevOpsLens AI — Automated Testing Guide

This guide explains the automated testing strategy, test fixtures, test isolation mechanisms, and instructions for running the complete test suite.

---

## 1. Testing Philosophy and Guarantees

DevOpsLens AI achieves **90% code coverage** across the application core. The test suite guarantees:
1. **100% Offline Execution:** Tests require zero external network calls, paid subscriptions, or real cloud API keys.
2. **Zero Test Pollution:** Every integration test executes against an isolated temporary SQLite database created in a unique temporary directory, guaranteeing that tests never modify production or development databases.
3. **No Flaky Tests:** External LLM timeouts, network failures, and API status errors are thoroughly verified using deterministic unit mocks.
4. **Fast Feedback Loop:** The complete 33-test suite executes in less than **1.0 second**.

---

## 2. Test Execution Commands

### Run the entire test suite
```bash
pytest -v
```

### Run tests with detailed code coverage report
```bash
pytest -v --cov=app --cov-report=term-missing
```

### Run a specific test module
```bash
pytest tests/test_parser.py -v
pytest tests/test_analyzer.py -v
pytest tests/test_api.py -v
```

### Run a specific single test
```bash
pytest tests/test_api.py -k "test_analyze_valid_log_file" -v
```

---

## 3. Test Suite Inventory (33 Verified Tests)

### 3.1. Parsing Engine Tests (`tests/test_parser.py` — 5 tests)
- `test_parse_all_severity_levels`: Verifies that `DEBUG`, `INFO`, `WARN`, `WARNING`, `ERROR`, `CRIT`, `CRITICAL`, and `FATAL` are parsed and normalized into standard severity categories.
- `test_parse_timestamp_formats`: Verifies extraction of ISO-8601, Apache Common Log, and Syslog timestamps, as well as safe handling of lines with missing timestamps.
- `test_parse_component_extraction`: Verifies extraction of bracketed service tags (e.g. `[auth-service]`) and parenthesized modules (e.g. `(database_pool)`).
- `test_parse_unstructured_and_stack_trace_lines`: Verifies that Python tracebacks and unformatted text lines do not crash the parser and are classified as `UNSTRUCTURED`.
- `test_parse_text_preserves_line_numbers`: Verifies that 1-based source line numbers are accurately retained across multi-line log documents.

### 3.2. Analyzer and Priority Ranking Tests (`tests/test_analyzer.py` — 3 tests)
- `test_fingerprint_normalization`: Verifies that dynamic tokens (IPs, UUIDs, hex pointers, numeric IDs) are replaced with normalized placeholders (`<IP>`, `<UUID>`, `<NUM>`, `<HEX>`).
- `test_recurring_error_grouping`: Verifies that multiple occurrences of an error sharing a normalized signature group together, tracking `count`, `first_line`, `last_line`, and all `line_numbers`.
- `test_transparent_priority_scoring_rules`: Verifies the mathematical formula for `P1 - Critical`, `P2 - High`, `P3 - Medium`, and `P4 - Low` priority tiers, including base severity weights, frequency boosts, and critical keyword bonuses.

### 3.3. File Upload and Security Validation Tests (`tests/test_file_validator.py` — 7 tests)
- `test_validate_metadata_valid_extensions`: Confirms `.log`, `.txt`, `.LOG`, and `.TXT` pass validation.
- `test_validate_metadata_unsupported_extension`: Confirms non-log extensions (`.exe`, `.sh`) raise `FileValidationError` with HTTP 400.
- `test_validate_metadata_empty_file`: Confirms 0-byte uploads raise `FileValidationError` with HTTP 400.
- `test_validate_metadata_oversized_file`: Confirms uploads exceeding 5 MB raise `FileValidationError` with HTTP 413 (Payload Too Large).
- `test_read_and_validate_content_rejects_binary`: Confirms files containing null bytes (`\x00`) in the first 8 KB are rejected with HTTP 400 as disguised binaries.
- `test_read_and_validate_content_rejects_whitespace_only`: Confirms files containing only spaces/newlines are rejected with HTTP 400.
- `test_read_and_validate_content_safe_decoding`: Confirms non-UTF8 characters fall back cleanly to Latin-1 with character replacement without throwing server exceptions.

### 3.4. Database and Repository Tests (`tests/test_database.py` — 4 tests)
- `test_save_and_retrieve_analysis`: Verifies atomic persistence of an analysis master record and its associated error groups, followed by querying and deserialization of `line_numbers_json`.
- `test_get_analyses_pagination`: Verifies that `limit` and `offset` parameters correctly paginate history records ordered by `uploaded_at DESC`.
- `test_foreign_key_cascade_delete`: Verifies that deleting a parent analysis record in SQLite automatically cascades to delete all child `error_groups` via `ON DELETE CASCADE`.
- `test_transaction_rollback_on_failure`: Verifies that a transaction failure midway through an operation rolls back all changes, leaving no orphaned data.

### 3.5. AI Integration and Grounding Tests (`tests/test_ai_integration.py` — 5 tests)
- `test_heuristic_database_error_diagnosis`: Verifies that the built-in deterministic heuristic engine identifies database connection pool failures and generates concrete debugging steps.
- `test_heuristic_memory_error_diagnosis`: Verifies heuristic detection of OutOfMemory and Java heap space failures.
- `test_evidence_validator_detects_hallucinations`: Verifies that when an AI model cites log lines that do not exist in the input, the validator tags the line as `[Unverified citation]` and appends a warning to the confidence score.
- `test_external_ai_timeout_fallback_to_heuristic`: Simulates an external API timeout (`httpx.TimeoutException`) using a mock and confirms clean fallback to the heuristic engine without throwing an unhandled exception.
- `test_external_ai_http_500_fallback`: Simulates an external API 500 error and confirms graceful fallback.

### 3.6. REST API Integration Tests (`tests/test_api.py` — 9 tests)
- `test_health_endpoint`: Verifies `GET /health` returns 200 OK with `healthy` status and database connectivity.
- `test_analyze_valid_log_file`: Verifies `POST /analyze` parses, ranks, and persists an uploaded log file, returning HTTP 201 Created.
- `test_analyze_empty_file_returns_400`: Verifies `POST /analyze` rejects empty file streams with HTTP 400.
- `test_analyze_unsupported_extension_returns_400`: Verifies `POST /analyze` rejects unsupported extensions with HTTP 400.
- `test_get_analyses_and_details`: Verifies `GET /analyses` lists uploads and `GET /analyses/{id}` returns detailed results.
- `test_get_analysis_not_found`: Verifies `GET /analyses/nonexistent` returns HTTP 404 Not Found.
- `test_get_analysis_errors_with_filter`: Verifies `GET /analyses/{id}/errors?severity=CRITICAL` filters error groups by severity.
- `test_diagnose_endpoint`: Verifies `POST /analyze/diagnose` accepts an analysis ID and error group ID to return grounded triage.
- `test_export_analysis_json_and_csv`: Verifies `GET /analyses/{id}/export` correctly formats responses in both JSON and CSV formats.

---

## 4. Test Fixtures and Architecture (`tests/conftest.py`)

- **`temp_db_path`**: Uses Python's `tempfile.mkstemp` to generate a dedicated SQLite file for each test function. Initializes schemas via `init_db(custom_path)` and deletes the file during teardown.
- **`test_repo`**: Provides an instance of `AnalysisRepository` bound to the isolated temporary database.
- **`client`**: Configures a FastAPI `TestClient` with dependency overrides:
  ```python
  app.dependency_overrides[get_settings] = get_test_settings
  routes.get_repository = lambda: AnalysisRepository(db_path=temp_db_path)
  ```
  This guarantees that all API requests initiated by the test client interact solely with the isolated temporary database.
