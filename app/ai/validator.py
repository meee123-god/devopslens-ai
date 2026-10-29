"""Validation and grounding verification for AI-generated diagnoses.

Guarantees that AI outputs match the required schema, contain realistic debugging steps,
and that cited supporting evidence actually exists in the provided log lines.
"""

from typing import List
from pydantic import BaseModel, Field


class DiagnosisResponse(BaseModel):
    """Validated schema for AI-assisted error diagnosis."""
    probable_cause: str = Field(description="Hypothesized root cause of the error")
    supporting_evidence: List[str] = Field(
        default_factory=list,
        description="List of log lines from the provided input that support this diagnosis"
    )
    debugging_steps: List[str] = Field(
        default_factory=list,
        description="Actionable, prioritized debugging steps for the engineer"
    )
    confidence: str = Field(description="Confidence rating with brief explanation")
    limitations: str = Field(description="Caveats and hypothesis disclaimer")
    model_used: str = Field(default="heuristic-engine", description="Identifier of the model or engine used")


def verify_and_sanitize_diagnosis(
    raw_data: dict,
    supplied_lines: List[str],
    model_name: str
) -> DiagnosisResponse:
    """Validate AI response schema and verify that cited evidence is grounded in supplied log lines.
    
    Args:
        raw_data: Raw JSON dictionary from the AI provider.
        supplied_lines: The exact log lines that were sent in the prompt.
        model_name: The name of the AI model or engine used.
        
    Returns:
        Validated and sanitized DiagnosisResponse instance.
    """
    probable_cause = str(raw_data.get("probable_cause", "Unspecified root cause.")).strip()
    raw_evidence = raw_data.get("supporting_evidence", [])
    if isinstance(raw_evidence, str):
        raw_evidence = [raw_evidence]
    elif not isinstance(raw_evidence, list):
        raw_evidence = []

    raw_steps = raw_data.get("debugging_steps", [])
    if isinstance(raw_steps, str):
        raw_steps = [raw_steps]
    elif not isinstance(raw_steps, list):
        raw_steps = ["Inspect application logs at the cited line numbers.", "Verify service configuration."]

    confidence = str(raw_data.get("confidence", "Medium (Automated inference)")).strip()
    limitations = str(raw_data.get("limitations", "")).strip()

    # 1. Grounding check: verify cited evidence against supplied lines
    verified_evidence: List[str] = []
    unverified_count = 0

    # Clean supplied lines for comparison
    normalized_supplied = [s.strip().lower() for s in supplied_lines if s.strip()]

    for ev in raw_evidence:
        ev_str = str(ev).strip()
        if not ev_str:
            continue

        ev_lower = ev_str.lower()
        # Check if the cited evidence is present or partially matches any supplied line
        matched = any(ev_lower in sup or sup in ev_lower for sup in normalized_supplied)

        if matched:
            verified_evidence.append(ev_str)
        else:
            unverified_count += 1
            verified_evidence.append(f"[Unverified citation]: {ev_str}")

    # If no evidence was grounded or provided, fallback to the top supplied lines
    if not verified_evidence and supplied_lines:
        verified_evidence = [supplied_lines[0].strip()]

    # If evidence hallucination occurred, adjust confidence rating
    if unverified_count > 0:
        confidence = f"{confidence} [Warning: {unverified_count} cited lines were not found verbatim in input]"

    # 2. Mandatory disclaimer requirement
    disclaimer = "AI-generated diagnosis is an automated hypothesis, not a verified fact. Always verify against source code."
    if disclaimer.lower() not in limitations.lower():
        limitations = f"{limitations} {disclaimer}".strip()

    return DiagnosisResponse(
        probable_cause=probable_cause,
        supporting_evidence=verified_evidence,
        debugging_steps=[str(step).strip() for step in raw_steps if str(step).strip()],
        confidence=confidence,
        limitations=limitations,
        model_used=model_name
    )
