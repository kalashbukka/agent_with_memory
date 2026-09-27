"""The incident-response loop:
Hindsight RECALL (incident memories + user preferences) -> Groq analysis
-> automatic learning (incident knowledge + preferences) -> Hindsight RETAIN -> response."""

import asyncio
import json
import logging

from pydantic import ValidationError

from app.agent.memory_extractor import extract_memories
from app.agent.preference_learner import learn_preferences
from app.groq.client import GroqError, chat_json
from app.hindsight.client import HindsightError, recall_incident_memory, retain_incident_knowledge
from app.hindsight.preferences import PreferenceProfile, load_profile
from app.schemas import AutoMemoryResult, IncidentAnalysis, IncidentInput, PreferenceResult, RecallResult

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior Site Reliability Engineer acting as an incident-response agent.
You analyze production incidents and recommend diagnostic checks and fixes. You never execute commands;
you only recommend. You have access to the team's historical incident memory (recalled from Hindsight).
Treat historical incidents as evidence, not as answers: a previous root cause is NOT automatically the
current root cause. Always compare, and call out what is different now.

Respond with a single JSON object with exactly these keys:
{
  "summary": string,
  "possible_causes": [{"cause": string, "likelihood": "High"|"Medium"|"Low", "evidence": string}],
  "historical_matches": [{"incident": string, "similarities": [string], "differences": [string], "how_it_applies": string}],
  "recommended_checks": [string],
  "recommended_solution": string,
  "confidence": "High"|"Medium"|"Low",
  "confidence_reason": string
}
If no historical memory was provided, "historical_matches" must be an empty list and you must not
invent past incidents.
The user's long-term preferences (if given) must be applied to the text you write in every field
(e.g. how the summary ends, language, level of detail, style), while keeping this exact JSON structure.
The current instruction overrides a stored preference when they conflict."""


def format_incident(incident: IncidentInput) -> str:
    return "\n".join(
        [
            f"Title: {incident.title}",
            f"Service: {incident.service}",
            f"Environment: {incident.environment}",
            f"Severity: {incident.severity.value}",
            f"Symptoms: {incident.symptoms}",
            f"Error logs: {incident.error_logs or '(none provided)'}",
            f"Recent changes: {incident.recent_changes or '(none provided)'}",
        ]
    )


def format_memory(recall: RecallResult) -> str:
    if recall.status == "error":
        return "(Hindsight memory could not be retrieved for this analysis - analyze without history.)"
    if recall.status == "empty":
        return "(No relevant previous incidents exist in memory yet.)"
    blocks = []
    for i, m in enumerate(recall.memories, 1):
        status = f"resolved={m.resolved_at}" if m.confirmed else "status=analyzed, resolution NOT confirmed"
        lines = [f"[Historical incident {i}] {m.title or 'Untitled'} (service={m.service}, env={m.environment}, severity={m.severity}, {status})"]
        if m.root_cause:
            lines.append(f"  {'Confirmed root cause' if m.confirmed else 'Root cause'}: {m.root_cause}")
        if m.solution:
            lines.append(f"  {'Solution applied' if m.confirmed else 'Fix'}: {m.solution}")
        if m.failed_approaches:
            lines.append(f"  Approaches that failed: {m.failed_approaches}")
        if m.outcome:
            lines.append(f"  Outcome: {m.outcome}")
        lines.append("  Facts recalled from memory:")
        lines += [f"   - {f.text}" for f in m.facts[:8]]
        blocks.append("\n".join(lines))
    if recall.other_facts:
        blocks.append("[Other related facts]\n" + "\n".join(f"   - {f.text}" for f in recall.other_facts))
    return "\n\n".join(blocks)


def format_preferences(profile: PreferenceProfile | None) -> str:
    if profile is None:
        return "(The user's preferences could not be loaded from memory.)"
    if not profile.preferences:
        return "(No long-term preferences stored for this user yet.)"
    return "\n".join(f"- {p.preference}" for p in profile.preferences)


def format_additional_instructions(incident: IncidentInput) -> str:
    if not incident.additional_instructions:
        return ""
    return f"""

ADDITIONAL INSTRUCTIONS FROM THE USER:

{incident.additional_instructions}

Follow these where they apply (they override the long-term preferences if they conflict),
but still return the JSON object described in the system prompt."""


def build_prompt(incident: IncidentInput, recall: RecallResult, profile: PreferenceProfile | None = None) -> str:
    return f"""CURRENT INCIDENT:

{format_incident(incident)}

RELEVANT HISTORICAL INCIDENT MEMORY:

{format_memory(recall)}

USER'S LONG-TERM PREFERENCES (recalled from memory; apply to every response):

{format_preferences(profile)}

INSTRUCTIONS:

Analyze the current incident.
Use historical incidents as supporting evidence.
Do not assume that a previous root cause is automatically the current root cause.
Compare the current incident with historical incidents.
Identify similarities and differences.
If a previous fix worked, say whether and why it may or may not be sufficient now (e.g. changed load).
If a previous approach failed, advise against repeating it.

Return:
1. Summary
2. Possible causes
3. Relevant historical incidents
4. Recommended checks
5. Recommended solution
6. Confidence

Return only the JSON object described in the system prompt.{format_additional_instructions(incident)}"""


async def _analyze_with_groq(incident: IncidentInput, recall: RecallResult, prompt: str) -> IncidentAnalysis:
    last_error: Exception | None = None
    for attempt in range(2):  # one retry on invalid output
        data = await chat_json(SYSTEM_PROMPT, prompt)
        try:
            analysis = IncidentAnalysis.model_validate(data)
            if recall.status != "ok":
                analysis.historical_matches = []  # never show invented history
            return analysis
        except ValidationError as exc:
            last_error = exc
            log.warning("Groq response failed validation (attempt %d): %s", attempt + 1, json.dumps(data)[:500])
    raise GroqError(f"Groq returned an analysis that failed validation: {last_error}")


async def remember(
    incident: IncidentInput, incident_id: str, analysis: IncidentAnalysis, recall: RecallResult, bank_id: str
) -> AutoMemoryResult:
    """Automatically decide what is worth remembering and retain it. Never fails the analysis."""
    try:
        items, reason, root_cause, fix = await extract_memories(incident, analysis, recall)
    except GroqError as exc:
        log.warning("Memory extraction failed for %s: %s", incident_id, exc)
        return AutoMemoryResult(status="error", message=f"Memory extraction failed ({exc}); nothing was stored.")
    if not items:
        return AutoMemoryResult(status="skipped", message=f"Nothing new stored in Hindsight: {reason}")
    try:
        await retain_incident_knowledge(incident, incident_id, items, root_cause, fix, bank_id)
    except HindsightError as exc:
        return AutoMemoryResult(status="error", message=f"{exc}; the extracted knowledge was not stored.", items=items)
    log.info("Auto-retained %d knowledge items for %s", len(items), incident_id)
    return AutoMemoryResult(
        status="stored", message=f"{len(items)} knowledge item(s) stored in Hindsight automatically.", items=items
    )


async def _load_preferences(bank_id: str) -> PreferenceProfile | None:
    try:
        return await load_profile(bank_id)
    except HindsightError as exc:
        log.warning("Preference recall failed: %s", exc)
        return None


async def analyze(
    incident: IncidentInput, bank_id: str, incident_id: str
) -> tuple[IncidentAnalysis, RecallResult, str, AutoMemoryResult, PreferenceResult]:
    """RECALL (incidents + preferences, user's own bank) -> Groq -> learn -> RETAIN.
    Raises GroqError if the analysis itself fails; learning failures never fail the analysis."""
    recall, profile = await asyncio.gather(recall_incident_memory(incident, bank_id), _load_preferences(bank_id))
    log.info("Hindsight recall: %s | preferences: %s", recall.message, None if profile is None else len(profile.preferences))
    prompt = build_prompt(incident, recall, profile)
    analysis = await _analyze_with_groq(incident, recall, prompt)

    memory, (changes, pref_error) = await asyncio.gather(
        remember(incident, incident_id, analysis, recall, bank_id),
        learn_preferences(bank_id, incident.additional_instructions),
    )
    applied = [p.preference for p in profile.preferences] if profile else []
    if profile is None:
        prefs = PreferenceResult(status="error", message="Your preferences could not be loaded from Hindsight.")
    else:
        msg = f"{len(applied)} long-term preference(s) applied." if applied else "No long-term preferences stored yet."
        if changes:
            msg += " Updated: " + "; ".join(f"{c.action} '{c.preference}'" for c in changes)
        if pref_error:
            msg += f" ({pref_error})"
        prefs = PreferenceResult(status="ok", message=msg, applied=applied, changes=changes)
    return analysis, recall, prompt, memory, prefs
