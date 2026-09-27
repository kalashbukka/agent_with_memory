"""Hindsight memory layer (official `hindsight-client` SDK, Hindsight Cloud).

- recall_incident_memory(): Hindsight RECALL for knowledge relevant to a new incident
- retain_incident_resolution(): Hindsight RETAIN of a resolved incident's knowledge
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any

from hindsight_client import Hindsight

from app.config import get_settings
from app.schemas import AutoMemoryItem, IncidentInput, RecallResult, RecalledFact, RecalledIncident, ResolutionInput

log = logging.getLogger(__name__)

# Every incident memory is tagged with this, so recall only ever searches incident knowledge.
INCIDENT_TAG = "kind:incident-resolution"
# Metadata "memory_source" values. Memories without it predate auto-memory and came from resolutions.
SOURCE_AUTO = "auto-analysis"
SOURCE_RESOLUTION = "confirmed-resolution"

BANK_MISSION = (
    "You are the long-term memory of an SRE / DevOps incident-response agent. "
    "Remember production incidents: affected service and environment, symptoms, error signatures, "
    "confirmed root causes, fixes that worked, fixes that failed, outcomes and lessons learned."
)
RETAIN_MISSION = (
    "Extract durable incident-response knowledge: which service had which symptoms and errors, the "
    "confirmed root cause, the solution applied, approaches that did not work, the outcome, and lessons. "
    "Ignore UI or login activity."
)


class HindsightError(Exception):
    pass


_client: Hindsight | None = None


def _get_client() -> Hindsight:
    global _client
    s = get_settings()
    if not s.hindsight_api_key:
        raise HindsightError("HINDSIGHT_API_KEY is not configured on the server.")
    if _client is None:
        _client = Hindsight(
            base_url=s.hindsight_base_url,
            api_key=s.hindsight_api_key,
            timeout=s.hindsight_timeout_seconds,
            max_attempts=2,
        )
    return _client


def _describe(exc: Exception) -> str:
    status = getattr(exc, "status", None)
    reason = getattr(exc, "reason", None) or type(exc).__name__
    if status == 401 or status == 403:
        return f"authentication failed ({status}) - check HINDSIGHT_API_KEY"
    if status:
        return f"HTTP {status} {reason}"
    return f"{reason}: {str(exc)[:200]}"


_ready_banks: set[str] = set()


async def ensure_bank(bank_id: str) -> bool:
    """Create/update a user's private memory bank (idempotent upsert). Returns True if ready."""
    if bank_id in _ready_banks:
        return True
    try:
        await _get_client().acreate_bank(
            bank_id=bank_id,
            name="Incident Response Agent",
            mission=BANK_MISSION,
            retain_mission=RETAIN_MISSION,
        )
    except Exception as exc:  # noqa: BLE001 - recall/retain report errors to the user
        log.warning("Could not ensure Hindsight bank %s: %s", bank_id, _describe(exc))
        return False
    _ready_banks.add(bank_id)
    log.info("Hindsight bank '%s' ready", bank_id)
    return True


async def health(bank_id: str | None = None) -> dict[str, Any]:
    """Connectivity check. With bank_id, also reports that (user's) bank's memory count."""
    try:
        client = _get_client()
        if bank_id is None:
            version = await client.aget_version()
            return {"ok": True, "detail": f"reachable (API {version.api_version})"}
        await ensure_bank(bank_id)
        page = await client.alist_memories(bank_id=bank_id, limit=1)
        return {"ok": True, "detail": f"your memory bank is reachable ({page.total} memory units)", "memory_units": page.total}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": _describe(exc) if not isinstance(exc, HindsightError) else str(exc)}


# ---------------------------------------------------------------- recall


def build_recall_query(incident: IncidentInput) -> str:
    parts = [
        f"Previous incidents, root causes, solutions, failed fixes and outcomes for service {incident.service}",
        f"similar to: {incident.title}.",
        f"Symptoms: {incident.symptoms}",
    ]
    if incident.error_logs:
        parts.append(f"Errors: {incident.error_logs[:600]}")
    if incident.recent_changes:
        parts.append(f"Recent changes: {incident.recent_changes[:300]}")
    return " ".join(parts)


_WORD = re.compile(r"[a-z0-9][a-z0-9_.-]{2,}")
_STOP = {
    "the", "and", "for", "with", "are", "was", "were", "from", "that", "this", "after", "into", "have",
    "has", "not", "but", "too", "very", "again", "than", "then", "our", "all", "any", "requests", "request",
}


def _keywords(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


def _why_relevant(incident: IncidentInput, prev: RecalledIncident, score: float | None) -> list[str]:
    reasons: list[str] = []
    if prev.service and prev.service.lower() == incident.service.lower():
        reasons.append(f"Same service: {incident.service}")
    if prev.environment and prev.environment.lower() == incident.environment.lower():
        reasons.append(f"Same environment: {incident.environment}")
    current = _keywords(f"{incident.title} {incident.symptoms} {incident.error_logs} {incident.recent_changes}")
    previous = _keywords(" ".join(filter(None, [prev.title, prev.root_cause, prev.solution] + [f.text for f in prev.facts])))
    shared = sorted(current & previous - _keywords(incident.service))
    if shared:
        reasons.append("Shared signals: " + ", ".join(shared[:8]))
    if score is not None:
        reasons.append(f"Hindsight relevance score: {score:.2f}")
    return reasons


def _score(r: Any) -> float | None:
    scores = getattr(r, "scores", None)
    if scores is None:
        return None
    return scores.reranker if scores.reranker is not None else scores.final


async def recall_incident_memory(incident: IncidentInput, bank_id: str) -> RecallResult:
    """RECALL from the authenticated user's own bank only."""
    s = get_settings()
    query = build_recall_query(incident)
    try:
        await ensure_bank(bank_id)
        resp = await _get_client().arecall(
            bank_id=bank_id,
            query=query,
            budget="mid",
            max_tokens=4096,
            tags=[INCIDENT_TAG],
            tags_match="any_strict",
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Hindsight recall failed")
        return RecallResult(
            status="error",
            message=f"Historical memory could not be retrieved from Hindsight ({_describe(exc)}). "
            "The analysis below uses the current incident only.",
            query=query,
        )

    # Group recalled facts by the incident they came from. An incident can have an auto-extracted
    # analysis memory and a confirmed resolution memory; confirmed details take precedence.
    grouped: dict[str, RecalledIncident] = {}
    loose: list[RecalledFact] = []
    for r in resp.results:
        fact = RecalledFact(text=r.text, type=r.type, score=_score(r))
        meta = r.metadata or {}
        doc = meta.get("incident_id") or r.document_id
        if not doc:
            loose.append(fact)
            continue
        confirmed = meta.get("memory_source", SOURCE_RESOLUTION) != SOURCE_AUTO
        item = grouped.get(doc)
        if item is None or (confirmed and not item.confirmed):
            details = RecalledIncident(
                incident_id=meta.get("incident_id", doc),
                title=meta.get("title"),
                service=meta.get("service"),
                environment=meta.get("environment"),
                severity=meta.get("severity"),
                root_cause=meta.get("root_cause") or None,
                solution=meta.get("solution") or None,
                outcome=meta.get("outcome") or None,
                failed_approaches=meta.get("failed_approaches") or None,
                resolved_at=meta.get("resolved_at") or None,
                confirmed=confirmed,
            )
            if item is not None:
                details.facts, details.relevance_score = item.facts, item.relevance_score
            item = grouped[doc] = details
        item.facts.append(fact)
        if fact.score is not None and (item.relevance_score is None or fact.score > item.relevance_score):
            item.relevance_score = fact.score

    # Keep only relevant incidents: same service, or strong semantic relevance for other services.
    relevant: list[RecalledIncident] = []
    for item in grouped.values():
        same_service = bool(item.service) and item.service.lower() == incident.service.lower()
        strong = item.relevance_score is not None and item.relevance_score >= s.hindsight_min_relevance
        if same_service or strong:
            item.why_relevant = _why_relevant(incident, item, item.relevance_score)
            relevant.append(item)
    relevant.sort(key=lambda m: (m.service == incident.service, m.relevance_score or 0), reverse=True)
    loose = [f for f in loose if f.score is None or f.score >= s.hindsight_min_relevance][:5]

    if not relevant and not loose:
        return RecallResult(
            status="empty",
            message="Hindsight was queried: no relevant previous incidents found in memory yet.",
            query=query,
        )
    n = len(relevant)
    return RecallResult(
        status="ok",
        message=f"{n} relevant previous incident{'s' if n != 1 else ''} recalled from Hindsight"
        + (f" (+{len(loose)} related facts)" if loose else ""),
        query=query,
        memories=relevant,
        other_facts=loose,
    )


# ---------------------------------------------------------------- retain


def build_memory_document(incident: dict[str, Any], resolution: ResolutionInput) -> str:
    lines = [
        f"Resolved production incident report: {incident['title']}",
        f"Service: {incident['service']}",
        f"Environment: {incident['environment']}",
        f"Severity: {incident['severity']}",
        f"Symptoms: {incident['symptoms']}",
    ]
    if incident.get("error_logs"):
        lines.append(f"Error logs / signatures: {incident['error_logs']}")
    if incident.get("recent_changes"):
        lines.append(f"Recent changes before the incident: {incident['recent_changes']}")
    lines += [
        f"Confirmed root cause: {resolution.root_cause}",
        f"Solution that resolved it: {resolution.solution}",
        f"Outcome: {resolution.outcome}",
    ]
    if resolution.failed_approaches:
        lines.append(f"Approaches that did NOT work: {resolution.failed_approaches}")
    if resolution.notes:
        lines.append(f"Lessons learned / notes: {resolution.notes}")
    return "\n".join(lines)


async def retain_incident_resolution(incident: dict[str, Any], resolution: ResolutionInput, bank_id: str) -> str:
    """Store the resolved incident in the user's own bank. Returns the memory document. Raises HindsightError."""
    document = build_memory_document(incident, resolution)
    resolved_at = datetime.now(timezone.utc)
    metadata = {
        "incident_id": incident["id"],
        "title": incident["title"][:200],
        "service": incident["service"],
        "environment": incident["environment"],
        "severity": incident["severity"],
        "root_cause": resolution.root_cause[:500],
        "solution": resolution.solution[:500],
        "outcome": resolution.outcome[:500],
        "failed_approaches": resolution.failed_approaches[:500],
        "resolved_at": resolved_at.isoformat(timespec="seconds"),
        "memory_source": SOURCE_RESOLUTION,
    }
    try:
        await ensure_bank(bank_id)
        resp = await _get_client().aretain(
            bank_id=bank_id,
            content=document,
            context="resolved production incident: symptoms, root cause, fix and outcome",
            document_id=incident["id"],
            timestamp=resolved_at,
            metadata=metadata,
            tags=[INCIDENT_TAG, f"service:{incident['service']}", f"env:{incident['environment']}"],
            retain_async=False,  # wait until stored so the next incident can recall it immediately
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Hindsight retain failed")
        raise HindsightError(f"Hindsight retain failed ({_describe(exc)})") from exc
    if not resp.success:
        raise HindsightError("Hindsight retain returned success=false")
    return document


def build_knowledge_document(incident: IncidentInput, items: list[AutoMemoryItem]) -> str:
    """Only the distilled knowledge items; never the raw incident text or logs."""
    header = (
        f"Incident-response knowledge for service {incident.service} ({incident.environment}), "
        f"from analysis of incident '{incident.title}'. Root causes and fixes are unconfirmed hypotheses "
        "unless stated otherwise."
    )
    return "\n".join([header] + [f"- [{i.category}] {i.content}" for i in items])


async def retain_incident_knowledge(
    incident: IncidentInput,
    incident_id: str,
    items: list[AutoMemoryItem],
    likely_root_cause: str,
    recommended_fix: str,
    bank_id: str,
) -> str:
    """Automatically retain knowledge extracted from an analysis. Raises HindsightError."""
    document = build_knowledge_document(incident, items)
    now = datetime.now(timezone.utc)
    metadata = {
        "incident_id": incident_id,
        "title": incident.title[:200],
        "service": incident.service,
        "environment": incident.environment,
        "severity": incident.severity.value,
        "root_cause": f"Suspected (unconfirmed): {likely_root_cause}" if likely_root_cause else "",
        "solution": f"Recommended (unconfirmed): {recommended_fix}" if recommended_fix else "",
        "memory_source": SOURCE_AUTO,
        "captured_at": now.isoformat(timespec="seconds"),
    }
    try:
        await ensure_bank(bank_id)
        resp = await _get_client().aretain(
            bank_id=bank_id,
            content=document,
            context="incident-response knowledge extracted automatically after an incident analysis",
            # Separate document from a later confirmed resolution (document_id=incident_id),
            # so neither replaces the other.
            document_id=f"{incident_id}:analysis",
            timestamp=now,
            metadata=metadata,
            tags=[INCIDENT_TAG, f"service:{incident.service}", f"env:{incident.environment}", f"source:{SOURCE_AUTO}"],
            # Queue fact extraction server-side so the user isn't kept waiting for it.
            retain_async=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Hindsight auto-retain failed")
        raise HindsightError(f"Hindsight retain failed ({_describe(exc)})") from exc
    if not resp.success:
        raise HindsightError("Hindsight retain returned success=false")
    return document
