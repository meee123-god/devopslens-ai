"""Prompt construction and data minimization templates for AI diagnosis.

Ensures only relevant error context is sent to external LLMs, protecting privacy
and enforcing structured JSON responses with grounded evidence.
"""

from typing import List


SYSTEM_INSTRUCTION = """
You are an expert DevOps Site Reliability Engineer (SRE) and software architect.
Your role is to diagnose software errors from application logs.

CRITICAL INSTRUCTIONS:
1. All diagnoses are HYPOTHESES, not verified facts.
2. In 'supporting_evidence', cite ONLY lines that appear in the supplied log snippet. Do NOT fabricate or extrapolate lines not present in the input.
3. Keep debugging steps concrete, actionable, and safe for production environments.
4. Return ONLY a valid JSON object matching the requested schema with no extra surrounding markdown or conversational commentary.
""".strip()


def build_triage_prompt(
    error_message: str,
    severity: str,
    occurrence_count: int,
    surrounding_lines: List[str]
) -> str:
    """Build a minimized, structured prompt for root-cause diagnosis.
    
    Args:
        error_message: Representative message of the error group.
        severity: Severity level (e.g. ERROR, CRITICAL).
        occurrence_count: Number of times this error occurred.
        surrounding_lines: Up to 10 surrounding log lines for context.
        
    Returns:
        Structured text prompt formatted for LLM consumption.
    """
    # Enforce data minimization: maximum 10 context lines
    context_slice = surrounding_lines[:10]
    formatted_context = "\n".join(f"  {line}" for line in context_slice) if context_slice else "  (No extra context lines provided)"

    prompt = f"""
Analyze the following recurring application issue:

Primary Error: {error_message}
Severity: {severity}
Occurrences in Log: {occurrence_count}

Relevant Log Excerpt (Data-minimized):
{formatted_context}

Please respond with a JSON object strictly adhering to this schema:
{{
  "probable_cause": "A concise explanation of the most likely technical root cause.",
  "supporting_evidence": ["Exact or closely matching log lines from the excerpt that support this hypothesis"],
  "debugging_steps": [
    "Step 1: Specific check or command",
    "Step 2: Specific verification or fix"
  ],
  "confidence": "High | Medium | Low (with brief rationale)",
  "limitations": "Explicit disclaimer that this diagnosis is a hypothesis requiring human inspection."
}}
""".strip()
    return prompt
