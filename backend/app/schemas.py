from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Severity(str, Enum):
    low = "Low"
    medium = "Medium"
    high = "High"
    critical = "Critical"


class IncidentInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=3, max_length=200)
    service: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._/-]+$")
    environment: str = Field(min_length=1, max_length=50)
    severity: Severity
    symptoms: str = Field(min_length=3, max_length=5000)
    error_logs: str = Field(default="", max_length=10000)
    recent_changes: str = Field(default="", max_length=5000)
    additional_instructions: str = Field(default="", max_length=2000)


class ResolutionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    root_cause: str = Field(min_length=3, max_length=2000)
    solution: str = Field(min_length=3, max_length=4000)
    outcome: str = Field(min_length=3, max_length=2000)
    failed_approaches: str = Field(default="", max_length=4000)
    notes: str = Field(default="", max_length=4000)


# ---------- Hindsight recall, shaped for the UI ----------


class RecalledFact(BaseModel):
    text: str
    type: str | None = None
    score: float | None = None


class RecalledIncident(BaseModel):
    """One previous incident recalled from Hindsight, with the facts Hindsight returned for it."""

    incident_id: str | None = None
    title: str | None = None
    service: str | None = None
    environment: str | None = None
    severity: str | None = None
    root_cause: str | None = None
    solution: str | None = None
    outcome: str | None = None
    failed_approaches: str | None = None
    resolved_at: str | None = None
    relevance_score: float | None = None
    # False when this knowledge was auto-extracted from an analysis and never confirmed by a resolution.
    confirmed: bool = True
    why_relevant: list[str] = []
    facts: list[RecalledFact] = []


class RecallResult(BaseModel):
    status: str  # "ok" | "empty" | "error"
    message: str
    query: str
    memories: list[RecalledIncident] = []
    other_facts: list[RecalledFact] = []  # relevant facts not tied to a specific incident document


# ---------- Groq analysis (validated with Pydantic) ----------


class PossibleCause(BaseModel):
    cause: str
    likelihood: str = "Medium"
    evidence: str = ""


class HistoricalMatch(BaseModel):
    incident: str
    similarities: list[str] = []
    differences: list[str] = []
    how_it_applies: str = ""


class IncidentAnalysis(BaseModel):
    summary: str
    possible_causes: list[PossibleCause] = []
    historical_matches: list[HistoricalMatch] = []
    recommended_checks: list[str] = []
    recommended_solution: str
    confidence: str = "Medium"
    confidence_reason: str = ""

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, v: object) -> str:
        s = str(v or "Medium").strip().capitalize()
        return s if s in {"Low", "Medium", "High"} else "Medium"


class AutoMemoryItem(BaseModel):
    category: str
    content: str


class AutoMemoryResult(BaseModel):
    """What the agent automatically decided to remember after this analysis."""

    status: str  # "stored" | "skipped" | "error"
    message: str
    items: list[AutoMemoryItem] = []


class PreferenceChange(BaseModel):
    action: str  # "added" | "updated" | "removed" | "learned"
    key: str
    preference: str


class PreferenceResult(BaseModel):
    """Long-term preferences recalled from Hindsight and applied, plus what was learned this time."""

    status: str  # "ok" | "error"
    message: str
    applied: list[str] = []
    changes: list[PreferenceChange] = []


class AnalyzeResponse(BaseModel):
    incident_id: str
    analysis: IncidentAnalysis
    recall: RecallResult
    model: str
    memory: AutoMemoryResult | None = None
    preferences: PreferenceResult | None = None


class ResolveResponse(BaseModel):
    incident_id: str
    retained: bool
    message: str
    bank_id: str
    memory_document: str
