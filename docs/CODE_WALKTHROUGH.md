# DevOpsLens AI — File-by-File Code Walkthrough

This document provides a detailed, technical explanation of every source code file in DevOpsLens AI. It is designed to prepare you to explain any class, function, parameter, or architectural pattern during a technical interview.

---

## 1. Application Configuration: `app/config.py`

### Purpose
Centralizes all application configurations using Pydantic's `BaseSettings`. Loads configurations from environment variables or a `.env` file, validates data types on application launch, and avoids hardcoding values.

### Key Classes & Functions
- **`class Settings(BaseSettings)`**:
  - `app_name: str` — Display title ("DevOpsLens AI").
  - `app_version: str` — Semantic version ("1.0.0").
  - `max_upload_size_bytes: int` — Configurable upload ceiling (default `5242880` bytes / 5 MB).
  - `allowed_extensions: List[str]` — Whitelist (`[".log", ".txt"]`).
  - `database_path: str` — Path to SQLite file (`"devopslens.db"`).
  - `ai_provider: str` — Active provider (`"offline"`, `"gemini"`, `"openai"`).
  - `ai_api_key: Optional[str]` — Secret key for external provider.
  - `ai_request_timeout_seconds: float` — Strict network timeout (`10.0`s).
  - `is_ai_enabled -> bool` — Computed property; returns `True` only if an API key is present and provider is not `"offline"`.
- **`get_settings() -> Settings`**:
  - Decorated with `@lru_cache()`. Creates a cached singleton instance of `Settings` so environment variables are parsed only once.

### Interview Talking Point
> *"We use Pydantic BaseSettings rather than raw `os.getenv` calls because it provides type safety, validation at application startup, and a single source of truth for the entire application."*

---

## 2. File Validation: `app/utils/file_validator.py`

### Purpose
Protects the server from malicious, oversized, binary, or malformed file uploads before files reach the parsing stage.

### Key Classes & Functions
- **`class FileValidationError(Exception)`**:
  - Custom domain exception holding both a descriptive error `message` and an appropriate HTTP `status_code` (e.g. 400 for bad extensions or 413 for oversized payloads).
- **`validate_file_metadata(filename: str, file_size: int) -> None`**:
  - Extracts the extension using `os.path.splitext` and lowercases it.
  - Rejects missing filenames, non-whitelisted extensions, 0-byte empty files, and files exceeding `MAX_UPLOAD_SIZE_BYTES`.
- **`read_and_validate_content(raw_bytes: bytes) -> str`**:
  - Checks the first 8 KB of the file for null bytes (`b"\x00"`). Null bytes indicate compiled executables (PE/ELF), images, or ZIP archives disguised as `.log`.
  - Attempts `utf-8` decoding first. If an international server log contains non-UTF8 characters, it gracefully falls back to `latin-1` with error replacement, ensuring the server never throws an unhandled `500` error on unexpected character encodings.

---

## 3. Log Parsing Engine: `app/services/parser.py`

### Purpose
Transforms unstructured raw text lines into structured, strongly typed `ParsedLogLine` dataclass instances with standard severity classifications, timestamps, components, and line numbers.

### Key Classes & Functions
- **`@dataclass class ParsedLogLine`**:
  - `line_number: int` — 1-based source line index.
  - `timestamp: Optional[str]` — Extracted timestamp string (or `None`).
  - `severity: str` — Standardized severity level.
  - `message: str` — Cleaned message without timestamp/severity prefixes.
  - `raw_line: str` — Exact verbatim source line (used for grounding checks).
  - `component: Optional[str]` — Extracted service or module name.
- **`class LogParser`**:
  - `SEVERITY_MAP`: Normalizes `WARN` $\to$ `WARNING`, `FATAL` / `CRIT` $\to$ `CRITICAL`.
  - `SEVERITY_PATTERN`: Regex with word boundaries `\b(DEBUG|INFO|WARN...)\b` to prevent false positive substring matching (e.g., word "information" won't match "INFO").
  - `_extract_timestamp(line: str) -> Optional[str]`: Evaluates three prioritized regex patterns:
    1. ISO-8601 (`YYYY-MM-DD HH:MM:SS`)
    2. Apache Common Log format (`[DD/Mon/YYYY:HH:MM:SS]`)
    3. Syslog format (`Mon DD HH:MM:SS`)
  - `parse_text(text: str) -> List[ParsedLogLine]`: Iterates over `text.splitlines()`, maintaining an incrementing `line_number`. Handles unparseable stack traces by classifying them as `UNSTRUCTURED` rather than crashing.

---

## 4. Analysis and Transparent Ranking: `app/services/analyzer.py`

### Purpose
Aggregates parsed log lines, creates reproducible fingerprints for recurring errors, groups them, and calculates transparent priority scores.

### Key Classes & Functions
- **`@dataclass class ErrorGroup`**:
  - Holds `fingerprint`, `severity`, `count`, `priority`, `score`, `sample_message`, `first_line`, `last_line`, `line_numbers`, and `scoring_explanation`.
- **`generate_fingerprint(message: str) -> str`**:
  - Replaces volatile dynamic parameters with normalized tokens:
    - UUIDs $\to$ `<UUID>`
    - Hex addresses $\to$ `<HEX>`
    - IP addresses and ports $\to$ `<IP>`
    - Quoted strings $\to$ `<STR>`
    - Numeric values $\to$ `<NUM>`
  - Result: Recurring errors with different user IDs or timestamps produce the exact same fingerprint string.
- **`calculate_priority(severity, count, sample_message) -> (priority, score, explanation)`**:
  - Computes:
    $$\text{Total Score} = \text{Base Severity Weight} + \text{Frequency Boost} + \text{Critical Keyword Boost}$$
  - **Base Severity:** `CRITICAL` = 100, `ERROR` = 60, `WARNING` = 30, `UNSTRUCTURED` = 10.
  - **Frequency Factor:** $\min(\text{count} \times 3, 40)$ points.
  - **Keyword Boost:** $+15$ points if message matches infrastructure keywords (`database`, `connection refused`, `deadlock`, `timeout`, `out of memory`, `fatal`).
  - **Tiers:** Score $\ge 110 \to$ `P1 - Critical`, $\ge 80 \to$ `P2 - High`, $\ge 45 \to$ `P3 - Medium`, $< 45 \to$ `P4 - Low`.

---

## 5. Database Connection and Schema: `app/database/connection.py`

### Purpose
Manages SQLite database connections, executes schema DDL migrations, enables Write-Ahead Logging (WAL) for concurrency, and enforces foreign key integrity.

### Key Functions
- **`get_db_connection(custom_path) -> Generator[sqlite3.Connection]`**:
  - Implemented as a Python context manager (`@contextmanager`).
  - Sets `conn.row_factory = sqlite3.Row` (allows dict-like access by column name).
  - Executes `PRAGMA foreign_keys = ON;` (critical because SQLite disables foreign keys by default).
  - Executes `PRAGMA journal_mode = WAL;` (Write-Ahead Logging allows simultaneous readers while a write occurs).
  - Calls `conn.commit()` upon successful exit or `conn.rollback()` if an exception occurs.
- **`init_db(custom_path) -> None`**:
  - Creates the `analyses`, `error_groups`, and `ai_diagnoses` tables and indexes if they do not exist.

---

## 6. Database Repository: `app/database/repository.py`

### Purpose
Implements the Repository Pattern, abstracting database SQL operations behind clean Python methods.

### Key Methods
- **`save_analysis(analysis_id, filename, result, execution_time_ms)`**:
  - Inserts summary into `analyses` and batch-inserts all error groups into `error_groups` using `executemany` within a single atomic transaction.
- **`get_analyses(limit, offset)`**:
  - Retrieves paginated past analyses sorted by `uploaded_at DESC`.
- **`get_analysis_by_id(analysis_id)`**:
  - Retrieves a single master record by primary key.
- **`get_error_groups(analysis_id, severity_filter)`**:
  - Retrieves ranked error groups for an analysis, deserializing `line_numbers_json` back into Python lists.
- **`save_ai_diagnosis(...)`**:
  - Persists AI root-cause diagnoses linked to both `analysis_id` and `error_group_id`.

---

## 7. AI Prompt Construction: `app/ai/prompts.py`

### Purpose
Builds structured prompts for root-cause analysis while enforcing **Data Minimization**.

### Key Functions
- **`build_triage_prompt(...)`**:
  - Enforces privacy and token limits by including only the representative error message, recurrence count, and up to 10 context lines. Never transmits the full log file.
  - Instructs the LLM to output pure JSON matching the diagnosis schema and explicitly warns against inventing unverified log lines.

---

## 8. AI Evidence Validation: `app/ai/validator.py`

### Purpose
Validates the AI response schema and enforces evidence grounding to prevent AI hallucinations from confusing engineers.

### Key Classes & Functions
- **`class DiagnosisResponse(BaseModel)`**:
  - Validates `probable_cause`, `supporting_evidence` (list of strings), `debugging_steps` (list of strings), `confidence`, and `limitations`.
- **`verify_and_sanitize_diagnosis(raw_data, supplied_lines, model_name)`**:
  - Loops over each line cited in `supporting_evidence`.
  - Checks if the cited line appears as a substring in any of the `supplied_lines`.
  - If a cited line is not found in the input, prefixes it with `[Unverified citation]` and appends a warning to the `confidence` rating.
  - Enforces inclusion of the disclaimer: *"AI-generated diagnosis is an automated hypothesis, not a verified fact."*

---

## 9. AI Triage Client: `app/ai/client.py`

### Purpose
Dispatcher that coordinates root-cause diagnosis across offline heuristic rules and external LLMs.

### Key Classes & Functions
- **`class AIDiagnosisClient`**:
  - **`diagnose_issue(...)`**: Main entry point. If `settings.is_ai_enabled` is False, calls `_heuristic_diagnosis`. If True, calls `_call_external_provider` inside a `try/except` block with a 10s timeout, falling back cleanly to `_heuristic_diagnosis` on network timeouts or API errors.
  - **`_heuristic_diagnosis(...)`**: Built-in deterministic expert engine. Matches known architectural failure signatures:
    - Database/Pool $\to$ Connection pool exhaustion / network drop.
    - Memory/OOM $\to$ Heap space exhaustion / memory leak.
    - Auth/JWT $\to$ Token expiration / invalid signature.
    - Timeout $\to$ Downstream latency / gateway timeout.
    - Filesystem $\to$ File not found / permission denied.
  - **`_call_external_provider(...)`**: Uses `httpx.Client(timeout=10.0)` to query Gemini or OpenAI REST endpoints with structured JSON responses.

---

## 10. API Routing and Schemas: `app/api/`

### `app/api/schemas.py`
Defines Pydantic request and response schemas:
- `HealthResponse`: System status, version, database connectivity, and AI mode.
- `AnalysisSummaryResponse`: High-level metrics (total lines, error counts, execution duration).
- `ErrorGroupResponse`: Priority, score, occurrences, sample message, line numbers.
- `AnalysisDetailResponse`: Summary combined with list of error groups.
- `DiagnoseRequest`: `analysis_id` and `error_group_id`.

### `app/api/routes.py`
Endpoints:
- `GET /health`: Health check and database connectivity probe.
- `POST /analyze`: Multipart file upload, validation, parsing, analysis, and persistence.
- `POST /analyze/diagnose`: Generates grounded root-cause diagnosis for a specific error group.
- `GET /analyses`: Paginated history of past analyses.
- `GET /analyses/{id}`: Full detail of an analysis.
- `GET /analyses/{id}/errors`: Error groups with optional `?severity=ERROR` filtering.
- `GET /analyses/{id}/export`: Exports analysis report in JSON or CSV format.

---

## 11. Application Entry Point: `app/main.py`

### Purpose
Initializes logging, manages startup/shutdown lifespan events, configures CORS middleware, and installs global exception filters.

### Key Logic
- **`lifespan(app)`**: Runs `init_db()` on application startup to ensure SQLite tables exist before any requests are served.
- **`global_exception_handler(request, exc)`**: Catches any unexpected unhandled Python exception, logs the stack trace to the console, and returns a sanitized `500 Internal Server Error` JSON response to prevent leaking internal code paths or credentials.

---

## 12. Frontend Dashboard: `frontend/`

### `frontend/api_client.py`
Encapsulates all HTTP communications using `requests`. Implements methods `check_health`, `analyze_log`, `get_analyses`, `get_analysis_details`, `request_diagnosis`, and `export_report`.

### `frontend/dashboard.py`
Streamlit application structured into 3 tabs:
1. **Log Analysis:** Uploads files or loads sample logs, displays metric KPI cards, renders Altair/Streamlit severity charts, lists filterable error tables with priority badges, triggers AI root-cause diagnosis, and provides JSON/CSV download buttons.
2. **Analysis History:** Displays a historical table of all saved analyses from SQLite with a one-click reload button.
3. **System Architecture:** Interactive reference guide covering the 6-tier architecture and priority scoring formula.
