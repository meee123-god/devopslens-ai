# DevOpsLens AI — Request Lifecycle and Data Flow

This document details the step-by-step lifecycle of requests through DevOpsLens AI, detailing the interactions between the frontend, API router, domain services, database, and AI engine.

---

## 1. Primary Request Flow: Log File Upload and Analysis (`POST /analyze`)

The diagram below illustrates what happens from the instant a user drops a `.log` file into Streamlit until the interactive report renders on screen.

```mermaid
sequenceDiagram
    autonumber
    actor User as SRE / Developer
    participant UI as Streamlit (dashboard.py)
    participant Client as API Client (api_client.py)
    participant API as FastAPI Router (routes.py)
    participant Val as File Validator (file_validator.py)
    participant Parser as Log Parser (parser.py)
    participant Analyzer as Log Analyzer (analyzer.py)
    participant Repo as Repository (repository.py)
    participant DB as SQLite (devopslens.db)

    User->>UI: Selects 'app.log' and clicks "Analyze Log File"
    UI->>Client: analyze_log(filename, raw_bytes)
    Client->>API: HTTP POST /analyze (multipart/form-data)
    
    rect rgb(240, 248, 255)
        Note over API,Val: 1. Input Validation Phase
        API->>Val: validate_file_metadata("app.log", byte_count)
        alt Extension != .log/.txt or Size > 5MB
            Val-->>API: raise FileValidationError (400/413)
            API-->>Client: HTTP 400/413 JSON {error, detail}
            Client-->>UI: Displays error banner
        end
        API->>Val: read_and_validate_content(raw_bytes)
        alt Binary null bytes detected or whitespace only
            Val-->>API: raise FileValidationError (400)
            API-->>Client: HTTP 400 JSON {error, detail}
        end
        Val-->>API: Returns safe decoded text string
    end

    rect rgb(255, 250, 240)
        Note over API,Analyzer: 2. Parsing & Analysis Phase
        API->>Parser: parse_text(text)
        loop For each line in text
            Parser->>Parser: Extract timestamp (ISO/Apache/Syslog)
            Parser->>Parser: Classify severity (DEBUG..CRITICAL..UNSTRUCTURED)
            Parser->>Parser: Extract bracketed component
            Parser->>Parser: Assign 1-indexed line number
        end
        Parser-->>API: List[ParsedLogLine]

        API->>Analyzer: analyze(parsed_lines)
        loop For each ERROR, CRITICAL, WARNING line
            Analyzer->>Analyzer: Normalize tokens (<IP>, <UUID>, <NUM>, <HEX>) -> Fingerprint
            Analyzer->>Analyzer: Group recurring occurrences & aggregate line numbers
            Analyzer->>Analyzer: Compute Priority Score: Base + Frequency + Keyword Boost
        end
        Analyzer-->>API: AnalysisResult (Counts + Ranked ErrorGroups)
    end

    rect rgb(245, 255, 245)
        Note over API,DB: 3. Persistence Phase (Atomic Transaction)
        API->>Repo: save_analysis(analysis_id, filename, result, execution_time_ms)
        Repo->>DB: BEGIN TRANSACTION
        Repo->>DB: INSERT INTO analyses (id, filename, total_lines, ...)
        Repo->>DB: INSERT INTO error_groups (analysis_id, fingerprint, score, ...)
        Repo->>DB: COMMIT TRANSACTION
        DB-->>Repo: Transaction Committed
        Repo-->>API: Persisted Summary Dict
    end

    API-->>Client: HTTP 201 Created (AnalysisDetailResponse JSON)
    Client-->>UI: Parsed Python dictionary
    UI->>User: Renders Summary Cards, Severity Bar Chart, and Triage Table
```

---

## 2. Secondary Request Flow: Root-Cause Diagnosis (`POST /analyze/diagnose`)

Triggered on-demand when a user clicks **"Run Root-Cause Diagnosis"** on an error group.

```mermaid
sequenceDiagram
    autonumber
    actor User as SRE / Developer
    participant UI as Streamlit (dashboard.py)
    participant Client as API Client (api_client.py)
    participant API as FastAPI Router (routes.py)
    participant Repo as Repository (repository.py)
    participant AIClient as AI Client (client.py)
    participant Validator as Evidence Validator (validator.py)
    participant ExtLLM as External LLM (Gemini/OpenAI)

    User->>UI: Clicks "Run Root-Cause Diagnosis" on Error Group #1
    UI->>Client: request_diagnosis(analysis_id, error_group_id)
    Client->>API: HTTP POST /analyze/diagnose {analysis_id, error_group_id}

    API->>Repo: get_analysis_by_id(analysis_id)
    alt Analysis not found
        Repo-->>API: None
        API-->>Client: HTTP 404 Not Found
    end

    API->>Repo: get_error_group_by_id(error_group_id)
    alt Error Group not found
        Repo-->>API: None
        API-->>Client: HTTP 404 Not Found
    end

    API->>AIClient: diagnose_issue(sample_message, severity, count, context_lines)

    alt External AI Enabled (AI_PROVIDER != 'offline' & Key Configured)
        AIClient->>ExtLLM: POST /chat/completions (timeout=10.0s)
        alt External LLM Timeout or HTTP 5xx Error
            ExtLLM-->>AIClient: TimeoutException / 500 Error
            AIClient->>AIClient: Log warning & trigger Heuristic Engine fallback
        else External LLM Returns JSON
            ExtLLM-->>AIClient: Raw JSON Output
        end
    else Offline Mode Active (Default)
        AIClient->>AIClient: Execute Rule-Based Deterministic Engine
    end

    AIClient->>Validator: verify_and_sanitize_diagnosis(raw_json, context_lines)
    Validator->>Validator: Verify cited supporting_evidence appears in context_lines
    alt Unverified / Hallucinated line detected
        Validator->>Validator: Prepend '[Unverified citation]' & downgrade confidence
    end
    Validator->>Validator: Enforce automated hypothesis disclaimer
    Validator-->>AIClient: Validated DiagnosisResponse

    AIClient-->>API: DiagnosisResponse
    API->>Repo: save_ai_diagnosis(analysis_id, error_group_id, diagnosis)
    API-->>Client: HTTP 200 OK (DiagnosisResponse JSON)
    Client-->>UI: Python dictionary
    UI->>User: Renders Grounded Root-Cause Card with Actionable Steps
```

---

## 3. Historical Query Flow: Browse Analyses (`GET /analyses`)

1. User switches to the **Analysis History** tab in Streamlit.
2. `dashboard.py` calls `api_client.get_analyses(limit=25, offset=0)`.
3. FastAPI receives `GET /analyses?limit=25&offset=0`.
4. `AnalysisRepository.get_analyses(limit=25, offset=0)` executes:
   ```sql
   SELECT id, filename, uploaded_at, total_lines, debug_count,
          info_count, warning_count, error_count, critical_count,
          unstructured_count, status, execution_time_ms
   FROM analyses
   ORDER BY uploaded_at DESC
   LIMIT ? OFFSET ?;
   ```
5. SQLite returns the recent records through Write-Ahead Log (WAL) reader without blocking active writers.
6. Pydantic validates and serializes each row into `List[AnalysisSummaryResponse]`.
7. Streamlit renders a sortable Pandas data table.
8. Selecting an analysis ID calls `GET /analyses/{id}` to fetch full error group details and restores the complete analysis state in the UI without re-uploading the file.
