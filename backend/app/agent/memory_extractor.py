"""Automatic memory extraction: after every analysis, decide what is worth remembering.

Groq distills the incident + analysis into a few short, durable knowledge items. Only those
items (never the raw incident text, logs or conversation) are retained in Hindsight.
"""

import logging
import re

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.groq.client import GroqError, chat_json
from app.schemas import AutoMemoryItem, IncidentAnalysis, IncidentInput, RecallResult

log = logging.getLogger(__name__)

CATEGORIES = {
    "root_cause",
    "resolution",
    "diagnostic_finding",
    "incident_pattern",
    "service_knowledge",
    "configuration_lesson",
    "team_instruction",
}

SYSTEM_PROMPT = """You curate the long-term memory of an SRE incident-response agent.
Given one incident and its analysis, decide what is worth remembering for FUTURE incident investigations.

Keep only durable, reusable knowledge, for example:
- root_cause: the most likely root cause (it is a hypothesis unless the input says it is confirmed)
- resolution: a fix/remediation that is recommended or known to work
- diagnostic_finding: an important signal, error signature or metric that pointed to the cause
- incident_pattern: a recurring pattern (e.g. "latency spikes on X after traffic increases")
- service_knowledge: technical facts about the service/dependencies (e.g. "payment-api uses a Redis pool of 150")
- configuration_lesson: a configuration-related lesson (limits, pool sizes, timeouts, flags)
- team_instruction: ONLY a standing rule/policy the user explicitly wrote in "User instructions"
  (e.g. "never restart the primary DB during business hours"). If the user instructions contain
  such a rule you MUST store it, quoted faithfully. Your own recommendations are never
  team_instruction. One-off formatting or answer-style requests (e.g. "answer in 3 bullets",
  "be brief") are temporary: do NOT store them.

Response-style preferences (summary endings, language, format, level of detail) are handled by a
separate preference memory: never store them as incident knowledge.

This incident is NOT resolved yet: phrase root_cause and resolution items as suspicions or
recommendations ("suspected", "recommended"), never as established facts.

Do NOT store: raw logs or whole incident text, conversation messages, UI events, temporary
instructions, generic advice that applies to any system, anything already listed under
ALREADY IN MEMORY, or sensitive data (credentials, tokens, keys, passwords, personal data,
emails, customer identifiers). Each item must be one self-contained sentence that names the
service. Prefer 0-5 items. It is fine to store nothing.

Respond with a JSON object:
{
  "worth_remembering": boolean,
  "reason": string,
  "likely_root_cause": string,   // short, "" if unknown
  "recommended_fix": string,     // short, "" if unknown
  "memories": [{"category": string, "content": string}]
}"""


class _Extraction(BaseModel):
    worth_remembering: bool = False
    reason: str = ""
    likely_root_cause: str = ""
    recommended_fix: str = ""
    memories: list[AutoMemoryItem] = Field(default_factory=list)

    @field_validator("memories", mode="before")
    @classmethod
    def keep_known_categories(cls, v: object) -> list:
        items = v if isinstance(v, list) else []
        return [
            i for i in items
            if isinstance(i, dict) and i.get("category") in CATEGORIES and str(i.get("content", "")).strip()
        ]


# Defense in depth: strip secrets/personal data even if the model lets them through.
_REDACTIONS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[REDACTED_KEY]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|client[_-]?secret)\b(\s*[:=]\s*)\S+"), r"\1\2[REDACTED]"),
    (re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"\b(sk|gsk|ghp|xox[abp])[-_][A-Za-z0-9-_]{16,}\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "[REDACTED_JWT]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[REDACTED_EMAIL]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[REDACTED_NUMBER]"),
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s:/@]+:[^\s@/]+@"), r"\1[REDACTED]@"),
]


# Analysis-time root causes and fixes are hypotheses; label them so recall never treats them as facts.
_UNCONFIRMED_PREFIX = {
    "root_cause": "Suspected root cause (unconfirmed):",
    "resolution": "Recommended fix (unconfirmed):",
}


def redact(text: str) -> str:
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text.strip()


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _already_known(recall: RecallResult) -> list[str]:
    facts = [f.text for m in recall.memories for f in m.facts] + [f.text for f in recall.other_facts]
    return facts[:25]


def _build_input(incident: IncidentInput, analysis: IncidentAnalysis, recall: RecallResult) -> str:
    known = _already_known(recall)
    causes = "\n".join(f"- {c.cause} ({c.likelihood}): {c.evidence}" for c in analysis.possible_causes)
    return f"""INCIDENT:
Title: {incident.title}
Service: {incident.service}
Environment: {incident.environment}
Severity: {incident.severity.value}
Symptoms: {incident.symptoms}
Error logs: {incident.error_logs[:1500] or '(none)'}
Recent changes: {incident.recent_changes or '(none)'}
User instructions given with this incident: {incident.additional_instructions or '(none)'}

ANALYSIS (not yet confirmed by the user):
Summary: {analysis.summary}
Possible causes:
{causes or '(none)'}
Recommended checks: {'; '.join(analysis.recommended_checks) or '(none)'}
Recommended solution: {analysis.recommended_solution}
Confidence: {analysis.confidence}

ALREADY IN MEMORY (do not repeat):
{chr(10).join('- ' + k for k in known) if known else '(nothing yet)'}

Return only the JSON object."""


async def extract_memories(
    incident: IncidentInput, analysis: IncidentAnalysis, recall: RecallResult
) -> tuple[list[AutoMemoryItem], str, str, str]:
    """Returns (items, reason, likely_root_cause, recommended_fix). Raises GroqError on failure."""
    data = await chat_json(SYSTEM_PROMPT, _build_input(incident, analysis, recall))
    try:
        ext = _Extraction.model_validate(data)
    except ValidationError as exc:
        raise GroqError(f"memory extraction returned invalid data: {exc.error_count()} errors") from exc
    if not ext.worth_remembering:
        return [], ext.reason or "Nothing new worth remembering.", "", ""

    known = {_normalize(k) for k in _already_known(recall)}
    instructions = _normalize(incident.additional_instructions)
    items: list[AutoMemoryItem] = []
    seen: set[str] = set()
    for item in ext.memories[:6]:
        content = redact(item.content)[:500]
        if item.category == "team_instruction" and not instructions:
            continue  # the user gave no instructions; this is the model's own advice
        if item.category in _UNCONFIRMED_PREFIX and "unconfirmed" not in content.lower():
            content = f"{_UNCONFIRMED_PREFIX[item.category]} {content}"
        key = _normalize(content)
        if len(key) < 12 or key in seen or key in known:
            continue  # empty, duplicate within this batch, or verbatim already in memory
        seen.add(key)
        items.append(AutoMemoryItem(category=item.category, content=content))
    return items, ext.reason, redact(ext.likely_root_cause)[:300], redact(ext.recommended_fix)[:300]
