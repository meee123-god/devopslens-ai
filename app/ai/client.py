"""AI triage client supporting both offline heuristic diagnosis and external LLM APIs.

Provides robust fallback behavior so the application functions completely even when
no external API key or internet connection is present.
"""

import json
from typing import List, Optional
import httpx
from app.config import get_settings
from app.ai.prompts import SYSTEM_INSTRUCTION, build_triage_prompt
from app.ai.validator import DiagnosisResponse, verify_and_sanitize_diagnosis
from app.utils.logger import get_logger

logger = get_logger(__name__)


class AIDiagnosisClient:
    """Client for generating grounded root-cause diagnoses for log incidents."""

    def __init__(self):
        self.settings = get_settings()

    def diagnose_issue(
        self,
        error_message: str,
        severity: str,
        occurrence_count: int,
        surrounding_lines: List[str]
    ) -> DiagnosisResponse:
        """Diagnose an error group using external AI if configured, or offline heuristics as fallback.
        
        Args:
            error_message: The primary error message.
            severity: Severity level (e.g. ERROR, CRITICAL).
            occurrence_count: Frequency of the error.
            surrounding_lines: Representative log lines for context.
            
        Returns:
            DiagnosisResponse schema with cause, evidence, steps, confidence, and limitations.
        """
        if self.settings.is_ai_enabled:
            try:
                logger.info(f"Invoking external AI provider '{self.settings.ai_provider}' for diagnosis.")
                return self._call_external_provider(
                    error_message=error_message,
                    severity=severity,
                    occurrence_count=occurrence_count,
                    surrounding_lines=surrounding_lines
                )
            except Exception as exc:
                # Log without exposing sensitive headers or parameters
                logger.warning(
                    f"External AI diagnosis call failed: {exc.__class__.__name__} - {str(exc)}. "
                    "Falling back to built-in heuristic diagnosis engine."
                )
                fallback = self._heuristic_diagnosis(
                    error_message=error_message,
                    severity=severity,
                    occurrence_count=occurrence_count,
                    surrounding_lines=surrounding_lines
                )
                fallback.limitations = (
                    f"[External AI unavailable: {exc.__class__.__name__}. Fallback engine used.] "
                    + fallback.limitations
                )
                return fallback

        # Default: Offline Heuristic Diagnoser
        return self._heuristic_diagnosis(
            error_message=error_message,
            severity=severity,
            occurrence_count=occurrence_count,
            surrounding_lines=surrounding_lines
        )

    def _heuristic_diagnosis(
        self,
        error_message: str,
        severity: str,
        occurrence_count: int,
        surrounding_lines: List[str]
    ) -> DiagnosisResponse:
        """Deterministic expert rule engine that infers likely causes from log signatures."""
        lower_msg = error_message.lower()
        evidence_slice = surrounding_lines[:3] if surrounding_lines else [error_message]

        if any(kw in lower_msg for kw in ["database", "pool", "connection refused", "deadlock", "postgres", "mysql"]):
            cause = "Database connectivity failure or connection pool exhaustion."
            steps = [
                "Verify database server process is running and accepting TCP connections.",
                "Check connection pool size limits in application configuration.",
                "Inspect database slow query logs and active transactions for locks/deadlocks.",
                "Validate database network security groups and firewall ingress rules."
            ]
            confidence = "High (Matches known database connection exhaustion pattern)"

        elif any(kw in lower_msg for kw in ["memory", "outofmemory", "heap", "oom"]):
            cause = "Memory exhaustion or memory leak in application runtime."
            steps = [
                "Inspect runtime heap memory usage and garbage collection metrics.",
                "Review recent commits for unclosed file streams, large cache maps, or unbounded queries.",
                "Temporarily increase container / JVM memory allocation limits.",
                "Generate and analyze a heap dump to locate memory-retaining objects."
            ]
            confidence = "High (Matches OutOfMemory/Heap failure pattern)"

        elif any(kw in lower_msg for kw in ["auth", "token", "unauthorized", "jwt", "forbidden", "401", "403"]):
            cause = "Authentication token expiration or invalid authorization credentials."
            steps = [
                "Verify JWT signing secret and token expiration TTL settings.",
                "Inspect client token renewal and refresh token workflow.",
                "Check server clock synchronization (NTP) to eliminate clock skew issues.",
                "Review role-based access control (RBAC) permission mappings for this endpoint."
            ]
            confidence = "High (Matches authentication/authorization failure pattern)"

        elif any(kw in lower_msg for kw in ["timeout", "timed out", "504", "gateway"]):
            cause = "Upstream service latency or network timeout."
            steps = [
                "Check response times and latency metrics of downstream dependencies.",
                "Review client-side HTTP timeout configurations and adjust if appropriate.",
                "Implement circuit breaker and exponential backoff retry patterns.",
                "Check network routing and proxy/gateway health."
            ]
            confidence = "Medium (Network timeouts can originate from client, proxy, or server)"

        elif any(kw in lower_msg for kw in ["not found", "filenotfound", "enoent", "permission denied", "eacces"]):
            cause = "File system resource missing or insufficient process permissions."
            steps = [
                "Verify that the specified file path exists on the host/container filesystem.",
                "Check permissions of the process user executing the service.",
                "Ensure mounted storage volumes (e.g. Docker/Kubernetes PVCs) are mounted properly."
            ]
            confidence = "High (Matches filesystem access error pattern)"

        else:
            cause = f"Application runtime exception in {severity} level processing."
            steps = [
                "Locate the stack trace around the cited line numbers in the full log.",
                "Reproduce the error locally with identical input parameters.",
                "Check recent deployment diffs for changes touching this module.",
                "Add defensive null checks or input validation guards."
            ]
            confidence = "Medium (Generic application failure pattern)"

        limitations = (
            "Heuristic diagnosis generated by DevOpsLens deterministic rule engine. "
            "AI-generated diagnosis is an automated hypothesis, not a verified fact. "
            "Always verify against source code."
        )

        return DiagnosisResponse(
            probable_cause=cause,
            supporting_evidence=evidence_slice,
            debugging_steps=steps,
            confidence=confidence,
            limitations=limitations,
            model_used="devopslens-heuristic-engine-v1"
        )

    def _call_external_provider(
        self,
        error_message: str,
        severity: str,
        occurrence_count: int,
        surrounding_lines: List[str]
    ) -> DiagnosisResponse:
        """Call external LLM API (Google Gemini or OpenAI-compatible) with timeout and JSON enforcement."""
        provider = self.settings.ai_provider.lower()
        api_key = self.settings.ai_api_key

        if not api_key:
            raise ValueError("No AI API key configured for external provider.")

        prompt = build_triage_prompt(
            error_message=error_message,
            severity=severity,
            occurrence_count=occurrence_count,
            surrounding_lines=surrounding_lines
        )

        timeout = self.settings.ai_request_timeout_seconds

        if provider == "gemini":
            # Gemini REST API endpoint
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.settings.ai_model_name}:generateContent?key={api_key}"
            headers = {"Content-Type": "application/json"}
            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": f"{SYSTEM_INSTRUCTION}\n\n{prompt}"}
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.2,
                    "responseMimeType": "application/json"
                }
            }

            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                parsed_json = json.loads(raw_text)

        elif provider == "openai":
            # OpenAI-compatible chat completions endpoint
            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": self.settings.ai_model_name,
                "messages": [
                    {"role": "system", "content": SYSTEM_INSTRUCTION},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2,
                "response_format": {"type": "json_object"}
            }

            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                raw_text = data["choices"][0]["message"]["content"]
                parsed_json = json.loads(raw_text)

        else:
            raise ValueError(f"Unsupported AI provider '{provider}'. Use 'offline', 'gemini', or 'openai'.")

        return verify_and_sanitize_diagnosis(
            raw_data=parsed_json,
            supplied_lines=surrounding_lines,
            model_name=self.settings.ai_model_name
        )
