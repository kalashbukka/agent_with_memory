"""Incident endpoints. Every query is scoped to the authenticated user's user_id, and every
Hindsight recall/retain goes to that user's private memory bank."""

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.agent import incident_agent
from app.api.auth import User, current_user
from app.config import get_settings
from app.db import connect, now_iso, row_to_incident
from app.groq.client import GroqError
from app.hindsight.client import HindsightError, retain_incident_resolution
from app.schemas import AnalyzeResponse, IncidentInput, ResolutionInput, ResolveResponse

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


def _load(incident_id: str, user: User) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM incidents WHERE id = ? AND user_id = ?", (incident_id, user.id)
        ).fetchone()
    if row is None:  # also for incidents owned by other users: never reveal they exist
        raise HTTPException(404, "Incident not found")
    return row_to_incident(row)


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_incident(body: IncidentInput, user: User = Depends(current_user)) -> AnalyzeResponse:
    incident_id = "INC-" + uuid.uuid4().hex[:8].upper()
    try:
        analysis, recall, prompt, memory, preferences = await incident_agent.analyze(body, user.bank_id, incident_id)
    except GroqError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc

    model = get_settings().groq_model
    with connect() as conn:
        conn.execute(
            """INSERT INTO incidents (id, user_id, title, service, environment, severity, symptoms, error_logs,
               recent_changes, created_by, created_at, status, analysis_json, recall_json, groq_prompt, groq_model)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'analyzed', ?, ?, ?, ?)""",
            (
                incident_id, user.id, body.title, body.service, body.environment, body.severity.value, body.symptoms,
                body.error_logs, body.recent_changes, user.username, now_iso(),
                analysis.model_dump_json(), recall.model_dump_json(), prompt, model,
            ),
        )
    return AnalyzeResponse(incident_id=incident_id, analysis=analysis, recall=recall, model=model, memory=memory, preferences=preferences)


@router.post("/{incident_id}/resolve", response_model=ResolveResponse)
async def resolve_incident(incident_id: str, body: ResolutionInput, user: User = Depends(current_user)) -> ResolveResponse:
    incident = _load(incident_id, user)
    if incident["retained_in_hindsight"]:
        raise HTTPException(409, "This incident's resolution is already stored in Hindsight")
    try:
        document = await retain_incident_resolution(incident, body, user.bank_id)
    except HindsightError as exc:
        raise HTTPException(502, f"{exc}. The resolution was NOT saved to memory - please retry.") from exc

    with connect() as conn:
        conn.execute(
            """UPDATE incidents SET status='resolved', root_cause=?, solution=?, outcome=?, failed_approaches=?,
               notes=?, resolved_at=?, retained_in_hindsight=1 WHERE id=? AND user_id=?""",
            (body.root_cause, body.solution, body.outcome, body.failed_approaches, body.notes, now_iso(), incident_id, user.id),
        )
    return ResolveResponse(
        incident_id=incident_id,
        retained=True,
        bank_id=user.bank_id,
        message="Resolution retained in your Hindsight memory. Your future similar incidents will recall it.",
        memory_document=document,
    )


@router.get("")
def list_incidents(user: User = Depends(current_user)) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, title, service, environment, severity, status, created_at, root_cause, outcome,
               resolved_at, retained_in_hindsight FROM incidents WHERE user_id = ? ORDER BY created_at DESC""",
            (user.id,),
        ).fetchall()
    return [dict(r) | {"retained_in_hindsight": bool(r["retained_in_hindsight"])} for r in rows]


@router.get("/{incident_id}")
def get_incident(incident_id: str, user: User = Depends(current_user)) -> dict:
    return _load(incident_id, user)


@router.get("/{incident_id}/memories")
def get_incident_memories(incident_id: str, user: User = Depends(current_user)) -> dict:
    """What Hindsight recalled for this incident, and the exact prompt Groq received."""
    incident = _load(incident_id, user)
    return {"incident_id": incident_id, "recall": incident["recall"], "groq_prompt": incident["groq_prompt"]}
