"""
Pydantic contract for the prospecting engine: preset schema and API payloads.

Preset types describe what a vertical does. API types describe what the UI
sends and receives. The UI types are generated from FastAPI's OpenAPI document,
so keep field names stable.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

ToggleKind = Literal["bool", "int", "choice"]
SourceKind = Literal["apollo_people", "research_events", "csv"]
LlmQa = Literal["gemini", "cursor_score"]
ToggleStatus = Literal["default", "relaxed", "tightened", "changed"]

RunStatus = Literal[
    "queued",
    "running",
    "awaiting_enrich",
    "enriching",
    "needs_review",
    "complete",
    "budget_stopped",
    "error",
    "interrupted",
    "cancelled",
]

LeadState = Literal[
    "candidate",
    "blocked",
    "qa_failed",
    "llm_failed",
    "shortlisted",
    "rejected",
    "post_qa_failed",
    "needs_review",
    "approved",
    "pushed",
    "push_failed",
]


# ---------------------------------------------------------------------------
# Preset schema
# ---------------------------------------------------------------------------


class ToggleSpec(BaseModel):
    """
    One operator-facing switch. `relaxed_when` names the value that loosens a filter:
      bool: "on" or "off"; int: "lower" or "higher"; choice: one of `choices`.
    Leave it None for source or volume toggles that are not filters (no label shown).
    """

    id: str
    label: str
    kind: ToggleKind
    default: bool | int | str
    choices: Optional[list[str]] = None
    relaxed_when: Optional[str] = None

    @model_validator(mode="after")
    def _check_shape(self) -> "ToggleSpec":
        if self.kind == "bool":
            if not isinstance(self.default, bool):
                raise ValueError(f"toggle {self.id}: bool default must be bool")
            if self.relaxed_when not in (None, "on", "off"):
                raise ValueError(f"toggle {self.id}: bool relaxed_when must be on/off")
        elif self.kind == "int":
            if isinstance(self.default, bool) or not isinstance(self.default, int):
                raise ValueError(f"toggle {self.id}: int default must be int")
            if self.relaxed_when not in (None, "lower", "higher"):
                raise ValueError(f"toggle {self.id}: int relaxed_when must be lower/higher")
        else:
            if not self.choices or not isinstance(self.default, str) or self.default not in self.choices:
                raise ValueError(f"toggle {self.id}: choice default must be one of choices")
            if self.relaxed_when is not None and self.relaxed_when not in self.choices:
                raise ValueError(f"toggle {self.id}: choice relaxed_when must be one of choices")
        return self

    def status_for(self, value: bool | int | str) -> ToggleStatus:
        """Label a value against the default. Pure function, used by the API and the estimate."""
        if value == self.default:
            return "default"
        if self.relaxed_when is None:
            return "changed"
        if self.kind == "bool":
            return "relaxed" if value == (self.relaxed_when == "on") else "tightened"
        if self.kind == "int":
            if self.relaxed_when == "lower":
                return "relaxed" if value < self.default else "tightened"
            return "relaxed" if value > self.default else "tightened"
        return "relaxed" if value == self.relaxed_when else "tightened"


class Caps(BaseModel):
    """Volume limits. Zero means the vertical's default or unlimited where noted."""

    target: int = 0
    max_per_company: int = 0  # 0 = unlimited within a run
    max_pages: int = 0  # Apollo people pages per title chunk
    title_chunk: int = 0
    org_pages: int = 0  # Apollo organization search pages (1 credit each)
    events: int = 0  # sponsor research events
    segments: int = 0  # retired; kept so older run rows still load
    brands: int = 0  # brands kept per run (research lanes)
    queries_per_source: int = 0  # Tavily queries per event or segment
    tavily_batch: int = 8  # brands per Tavily spend search
    gemini_batch: int = 20  # rows per Gemini QA request


class SourceSpec(BaseModel):
    kind: SourceKind
    params: dict[str, Any] = Field(default_factory=dict)


class VerticalSpec(BaseModel):
    id: str
    label: str
    icp: str
    monday_vertical: str  # a label, or "from_research" when research sets it per brand
    source: SourceSpec
    gate_chain: str  # key into engine.gates.CHAINS
    llm_qa: Optional[LlmQa] = None
    toggles: list[ToggleSpec]
    caps: Caps

    @field_validator("toggles")
    @classmethod
    def _unique_toggles(cls, value: list[ToggleSpec]) -> list[ToggleSpec]:
        ids = [t.id for t in value]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate toggle id")
        return value


class CrmContract(BaseModel):
    """Monday board contract. Env names are read at runtime; defaults are code defaults."""

    board_id_env: str
    board_id_default: str
    # Set from the Preset screen. When non-empty it wins over the env var and the code default.
    board_id_override: str = ""
    new_leads_group_env: str
    new_leads_group_default: str
    new_leads_group_override: str = ""
    columns: dict[str, str]  # logical name -> Monday column id
    protected_group_ids: list[str]
    protected_status_labels: list[str]


class Preset(BaseModel):
    id: str
    name: str
    place: str
    year: int
    crm: CrmContract
    blacklist_path: str
    verticals: list[VerticalSpec]

    @model_validator(mode="after")
    def _unique_verticals(self) -> "Preset":
        ids = [v.id for v in self.verticals]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate vertical id")
        return self

    def vertical(self, vertical_id: str) -> VerticalSpec:
        for v in self.verticals:
            if v.id == vertical_id:
                return v
        raise KeyError(vertical_id)


# ---------------------------------------------------------------------------
# API payloads
# ---------------------------------------------------------------------------


class ToggleState(BaseModel):
    id: str
    label: str
    kind: ToggleKind
    value: bool | int | str
    default: bool | int | str
    choices: Optional[list[str]] = None
    status: ToggleStatus


class RunCreate(BaseModel):
    preset_id: str
    vertical_id: str
    toggles: dict[str, bool | int | str] = Field(default_factory=dict)
    caps: dict[str, int] = Field(default_factory=dict)
    brief: str = Field(default="", max_length=500)


class SpendLine(BaseModel):
    label: str
    units: Optional[float] = None  # None = measured later (after the free probe)
    note: str = ""


class ProviderEstimate(BaseModel):
    provider: str
    unit: str
    lines: list[SpendLine]
    total: Optional[float] = None
    month_to_date: float = 0
    reserved: float = 0
    ceiling: Optional[float] = None
    remaining: Optional[float] = None
    refreshes_on: Optional[str] = None  # YYYY-MM-DD, when this balance starts over
    blocker: Optional[str] = None


class Estimate(BaseModel):
    preset_id: str
    vertical_id: str
    toggles: list[ToggleState]
    providers: list[ProviderEstimate]
    blockers: list[str]
    can_start: bool
    note: str = ""


class GateStep(BaseModel):
    stage: int
    gate_id: str
    passed: bool
    reason: str = ""


class RunOut(BaseModel):
    id: str
    kind: Literal["discovery", "import"]
    preset_id: str
    vertical_id: str
    vertical_label: str
    status: RunStatus
    stage: int
    stage_name: str
    toggles: list[ToggleState]
    caps: dict[str, int]
    brief: str
    started_by: str
    error: str
    cancel_requested: bool
    counts: dict[str, int]
    spend: dict[str, float]
    reservation: dict[str, float]
    created_at: str
    updated_at: str


class LeadOut(BaseModel):
    id: str
    run_id: str
    seq: int
    state: LeadState
    shelf_brand: str
    person_name: str
    title: str
    email: str
    domain: str
    location: str
    vertical: str
    gates: list[GateStep]
    llm: Optional[dict[str, Any]] = None
    evidence: list[str] = Field(default_factory=list)
    cost_spent: float = 0
    decided_by: str = ""
    decided_at: str = ""
    monday_item_id: str = ""
    push_error: str = ""
    approvable: bool = False
    approve_blocker: str = ""


class EventOut(BaseModel):
    id: int
    run_id: str
    ts: str
    level: str
    message: str


class LeadBulkAction(BaseModel):
    action: Literal["reject", "restore", "approve"]
    lead_ids: list[str] = Field(min_length=1, max_length=500)


class RefusedLead(BaseModel):
    lead_id: str
    reason: str


class DecisionResult(BaseModel):
    updated: list[str]
    refused: list[RefusedLead]


class CrmStatus(BaseModel):
    board_id: str
    ttl_hours: float
    monday_key_set: bool
    fetched_at: Optional[str] = None
    age_hours: Optional[float] = None
    stale: bool
    board_rows: int


class Health(BaseModel):
    ok: bool
    db_path: str
    schema_version: int
    worker_alive: bool
    ui_built: bool
    live_push_enabled: bool = False
    board_contract_ok: bool = True
    board_contract_problems: list[str] = Field(default_factory=list)


class PushRequest(BaseModel):
    """A push writes to Monday. It also needs ENGINE_LIVE_PUSH_ENABLED. The UI confirms once first."""

    lead_ids: list[str] = Field(default_factory=list, max_length=500)


class PushRow(BaseModel):
    lead_id: str
    shelf_brand: str
    email: str
    outcome: Literal["created", "skipped", "failed", "already_pushed"]
    monday_item_id: str = ""
    reason: str = ""


class PushResult(BaseModel):
    live: bool
    rows: list[PushRow]
    message: str


class PersonTier(BaseModel):
    """One person-location tier. Tier 1 is searched first."""

    tier: int
    locations: list[str] = Field(default_factory=list)


class ToggleDefault(BaseModel):
    """A gate's saved default. `code_default` is the factory value, used only to label a change."""

    id: str
    label: str
    kind: ToggleKind
    value: bool | int | str
    code_default: bool | int | str
    choices: Optional[list[str]] = None
    relaxed_when: Optional[str] = None


class VerticalSettings(BaseModel):
    """Operator-facing search and default configuration for one vertical."""

    id: str
    label: str
    source_kind: str
    monday_vertical: str
    titles: list[str] = Field(default_factory=list)
    seniorities: list[str] = Field(default_factory=list)
    org_keyword_tags: list[str] = Field(default_factory=list)
    org_locations: list[str] = Field(default_factory=list)
    person_location_tiers: list[PersonTier] = Field(default_factory=list)
    florida_person_locations: list[str] = Field(default_factory=list)
    us_person_locations: list[str] = Field(default_factory=list)
    seed_path: str = ""
    caps: dict[str, int] = Field(default_factory=dict)
    toggles: list[ToggleDefault] = Field(default_factory=list)


class PresetSettings(BaseModel):
    """Everything the Preset screen can change. Code keeps the factory copy used by Reset."""

    board_id: str
    new_leads_group_id: str
    columns: dict[str, str]
    protected_group_ids: list[str]
    protected_status_labels: list[str]
    verticals: list[VerticalSettings]


# ---------------------------------------------------------------------------
# Validation helpers: payload -> frozen run plan
# ---------------------------------------------------------------------------


def resolve_toggle_values(vertical: VerticalSpec, overrides: dict[str, bool | int | str]) -> dict[str, bool | int | str]:
    """Defaults merged with overrides. Unknown ids and wrong types raise ValueError."""
    known = {t.id: t for t in vertical.toggles}
    for key in overrides:
        if key not in known:
            raise ValueError(f"unknown toggle {key!r} for {vertical.id}")
    values: dict[str, bool | int | str] = {}
    for spec in vertical.toggles:
        value = overrides.get(spec.id, spec.default)
        if spec.kind == "bool":
            if not isinstance(value, bool):
                raise ValueError(f"toggle {spec.id} must be true or false")
        elif spec.kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"toggle {spec.id} must be a whole number")
        else:
            if not isinstance(value, str) or value not in (spec.choices or []):
                raise ValueError(f"toggle {spec.id} must be one of {spec.choices}")
        values[spec.id] = value
    return values


def toggle_states(vertical: VerticalSpec, values: dict[str, bool | int | str]) -> list[ToggleState]:
    return [
        ToggleState(
            id=spec.id,
            label=spec.label,
            kind=spec.kind,
            value=values[spec.id],
            default=spec.default,
            choices=spec.choices,
            status=spec.status_for(values[spec.id]),
        )
        for spec in vertical.toggles
    ]


def resolve_caps(vertical: VerticalSpec, overrides: dict[str, int]) -> Caps:
    """Caps override only the fields a vertical already defines. Negative values are refused."""
    base = vertical.caps.model_dump()
    for key, value in overrides.items():
        if key not in base:
            raise ValueError(f"unknown cap {key!r}")
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"cap {key} must be a non-negative whole number")
        base[key] = value
    return Caps(**base)
