"""
Gate chains per vertical. Each gate is a small function of (lead context, gate env) that calls an existing
predicate from prospecting_qa, concert_series_qa, venue_rental_qa, or the research modules. The engine
composes predicates here and never re-implements one.

Chains are ordered tuples of (stage, gate_id). Stages follow the plan:
  1 = free (no paid data), 3 = firmographics (org data), 7 = post-enrich (contact data is final).
Every gate in a chain is evaluated so the trail is complete. The lead state comes from the earliest failing stage.

Slice 2 covers the gates that need only data a CSV can carry. Gates that need Apollo or Tavily
(org lookup, spend evidence, LLM QA, Cursor score) arrive in slices 3 and 5.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import prospecting_qa as pq
from apollo_contact_rank import sponsorship_title_score
from brand_targeting import is_corporate_holding_target
from concert_series_qa import concert_nonprofit_name_blocked, concert_org_viable, concert_title_gate
from engine.crm import Blocklist
from prospect_scoring import score_prospect
from sponsor_name_qa import is_plausible_brand_name
from venue_rental_qa import venue_title_gate

STAGE_FREE = 1
STAGE_FIRMOGRAPHICS = 3
STAGE_POST_ENRICH = 7

# Sponsor title score floor and the score that exempts a contact from the prospect-score floor.
TITLE_SCORE_FLOOR = 45
TITLE_SCORE_EXEMPT = 72

# Gates whose failure means "this contact is already on the board or blacklisted" (state "blocked").
BLOCKED_GATES = frozenset(
    {"duplicate_in_run", "blocklist_email", "blocklist_domain", "blocklist_company", "blocklist_name", "protected_account"}
)

# LLM verdicts that keep a row approvable. "fail" never does.
APPROVABLE_LLM_VERDICTS = ("pass", "flag")


@dataclass
class LeadCtx:
    """Everything a gate may read about one candidate. Built from a CSV row or, later, from Apollo."""

    vertical_label: str
    shelf_brand: str
    company: str
    first: str
    last: str
    title: str
    email: str  # normalized
    website: str = ""
    industry: str = ""
    annual_revenue: Any = None
    employees: Any = None
    city: str = ""
    state: str = ""
    country: str = ""
    org_city: str = ""
    org_state: str = ""
    org_country: str = ""

    @property
    def email_domain(self) -> str:
        return pq.email_domain_key(self.email)

    @property
    def org_name(self) -> str:
        return self.company or self.shelf_brand

    def person(self) -> dict[str, str]:
        return {"city": self.city, "state": self.state, "country": self.country}

    def org(self) -> dict[str, str]:
        return {
            "city": self.org_city or "",
            "state": self.org_state or "",
            "country": self.org_country or "",
            "website_url": self.website,
            "industry": self.industry,
        }


@dataclass
class GateEnv:
    blocklist: Blocklist
    toggles: dict[str, Any]
    seen_emails: set[str] = field(default_factory=set)
    company_counts: dict[str, int] = field(default_factory=dict)
    max_per_company: int = 0  # 0 = unlimited within the run

    def flag(self, name: str, default: bool) -> bool:
        value = self.toggles.get(name, default)
        return bool(value)

    def number(self, name: str, default: int) -> int:
        try:
            return int(self.toggles.get(name, default))
        except (TypeError, ValueError):
            return default


GateResult = tuple[bool, str]
GateFn = Callable[[LeadCtx, GateEnv], GateResult]


def _ok(passed: bool, reason: str) -> GateResult:
    return (True, "") if passed else (False, reason)


# ---------------------------------------------------------------------------
# Stage 1: free gates (no paid data)
# ---------------------------------------------------------------------------


def g_duplicate_in_run(ctx: LeadCtx, env: GateEnv) -> GateResult:
    if ctx.email and ctx.email in env.seen_emails:
        return _ok(False, "same email appears earlier in this run")
    return (True, "")


def g_email_present(ctx: LeadCtx, env: GateEnv) -> GateResult:
    return _ok(bool(ctx.email), "no email")


def g_email_blocked(ctx: LeadCtx, env: GateEnv) -> GateResult:
    reason = pq.email_blocked(ctx.email)
    return _ok(reason is None, reason or "")


def g_blocklist_email(ctx: LeadCtx, env: GateEnv) -> GateResult:
    reason = env.blocklist.email_hit(ctx.email)
    return _ok(reason is None, reason or "")


def g_blocklist_domain(ctx: LeadCtx, env: GateEnv) -> GateResult:
    reason = env.blocklist.domain_hit(ctx.email_domain, ctx.website)
    return _ok(reason is None, reason or "")


def g_blocklist_company(ctx: LeadCtx, env: GateEnv) -> GateResult:
    for name in (ctx.shelf_brand, ctx.company):
        reason = env.blocklist.company_hit(name)
        if reason:
            return (False, reason)
    return (True, "")


def g_brand_plausible(ctx: LeadCtx, env: GateEnv) -> GateResult:
    return _ok(bool(is_plausible_brand_name(ctx.shelf_brand)), "implausible brand name")


def g_not_holding_company(ctx: LeadCtx, env: GateEnv) -> GateResult:
    return _ok(not is_corporate_holding_target(ctx.shelf_brand), "holding company, not a shelf brand")


def g_title_gate(ctx: LeadCtx, env: GateEnv) -> GateResult:
    ok, reason = pq.title_gate(ctx.title)
    return _ok(ok, f"title: {reason}")


def g_concert_title(ctx: LeadCtx, env: GateEnv) -> GateResult:
    ok, reason = concert_title_gate(ctx.title)
    return _ok(ok, f"title: {reason}")


def g_venue_title(ctx: LeadCtx, env: GateEnv) -> GateResult:
    ok, reason = venue_title_gate(ctx.title)
    return _ok(ok, f"title: {reason}")


def g_concert_nonprofit_name(ctx: LeadCtx, env: GateEnv) -> GateResult:
    reason = concert_nonprofit_name_blocked(ctx.company)
    return _ok(reason is None, reason or "")


def g_protected_account(ctx: LeadCtx, env: GateEnv) -> GateResult:
    reason = env.blocklist.protected_hit(ctx.company or ctx.shelf_brand, ctx.website, ctx.email_domain)
    return _ok(reason is None, reason or "")


# ---------------------------------------------------------------------------
# Stage 3: firmographics (org data; CSV rows must carry the columns these need)
# ---------------------------------------------------------------------------


def g_org_name_blocked(ctx: LeadCtx, env: GateEnv) -> GateResult:
    reason = pq.org_name_blocked(ctx.org_name)
    return _ok(reason is None, reason or "")


def g_non_sponsor_org_name(ctx: LeadCtx, env: GateEnv) -> GateResult:
    reason = pq.non_sponsor_org_name_blocked(ctx.org_name)
    return _ok(reason is None, reason or "")


def g_out_of_market_hospital(ctx: LeadCtx, env: GateEnv) -> GateResult:
    reason = pq.out_of_market_hospital_blocked(ctx.org_name, ctx.org_state or ctx.state, ctx.org_city or ctx.city)
    return _ok(reason is None, reason or "")


def g_org_industry_for_brand(ctx: LeadCtx, env: GateEnv) -> GateResult:
    reason = pq.org_industry_blocked_for_brand(
        ctx.industry, shelf_brand=ctx.shelf_brand, org=ctx.org(), brand_domain=ctx.website
    )
    return _ok(reason is None, reason or "")


def g_sponsor_org_viable(ctx: LeadCtx, env: GateEnv) -> GateResult:
    ok, reason = pq.sponsor_org_viable(
        org_name=ctx.org_name,
        org_industry=ctx.industry,
        email=ctx.email,
        annual_revenue=ctx.annual_revenue,
        estimated_employees=ctx.employees,
        brand_mode=True,
        shelf_brand_name=ctx.shelf_brand,
        strict=True,
        min_revenue=env.number("min_brand_revenue", 10_000_000),
        min_employees=env.number("min_employees", 0),
    )
    return _ok(ok, reason)


def g_probable_name(ctx: LeadCtx, env: GateEnv) -> GateResult:
    """Obfuscated Apollo last names only. A full last name is judged by blocklist_name after enrich."""
    reason = env.blocklist.probable_name_hit(ctx.first, ctx.last, ctx.org_name)
    return _ok(reason is None, reason or "")


def g_concert_org_viable(ctx: LeadCtx, env: GateEnv) -> GateResult:
    ok, reason = concert_org_viable(
        org_name=ctx.org_name,
        org_industry=ctx.industry,
        email=ctx.email,
        annual_revenue=ctx.annual_revenue,
        estimated_employees=ctx.employees,
        min_revenue=env.number("min_revenue", 10_000_000),
        min_employees=env.number("min_employees", 51),
        strict=True,
    )
    return _ok(ok, reason)


# ---------------------------------------------------------------------------
# Stage 7: post-enrich (contact data is final; operator-supplied rows count as enriched)
# ---------------------------------------------------------------------------


def g_blocklist_name(ctx: LeadCtx, env: GateEnv) -> GateResult:
    reason = env.blocklist.name_hit(ctx.first, ctx.last)
    return _ok(reason is None, reason or "")


def g_geo_person_org(ctx: LeadCtx, env: GateEnv) -> GateResult:
    ok, reason = pq.geo_person_org_gate(
        ctx.person(),
        ctx.org(),
        require_us=env.flag("require_us", True),
        require_florida=env.flag("florida_person_only", True),
        person_florida_only=True,
        allow_global_org=env.flag("allow_global_org", True),
    )
    return _ok(ok, reason)


def g_title_score_min(ctx: LeadCtx, env: GateEnv) -> GateResult:
    score = sponsorship_title_score(ctx.title, shelf_brand=ctx.shelf_brand)
    return _ok(score >= TITLE_SCORE_FLOOR, f"title fit {score}/100 below {TITLE_SCORE_FLOOR}")


def g_prospect_score_min(ctx: LeadCtx, env: GateEnv) -> GateResult:
    title_pts = sponsorship_title_score(ctx.title, shelf_brand=ctx.shelf_brand)
    fit, _label = score_prospect(
        person={**ctx.person(), "seniority": ""},
        org=ctx.org(),
        title=ctx.title,
        shelf_brand=ctx.shelf_brand,
        category=ctx.vertical_label,
    )
    floor = env.number("min_contact_score", 55)
    passed = fit >= floor or title_pts >= TITLE_SCORE_EXEMPT
    return _ok(passed, f"prospect score {fit}/{floor} and title {title_pts} below {TITLE_SCORE_EXEMPT}")


def g_person_in_florida(ctx: LeadCtx, env: GateEnv) -> GateResult:
    if not env.flag("florida_person_only", True) or env.flag("us_fallback", False):
        return (True, "")  # the Florida person gate is off for this run
    in_florida = pq.person_in_florida({"city": ctx.city, "state": ctx.state})
    return _ok(in_florida, f"person not in Florida: {ctx.city or '?'} | {ctx.state or '?'}")


def g_max_per_company(ctx: LeadCtx, env: GateEnv) -> GateResult:
    key = pq.normalize_company_key(ctx.org_name)
    cap = env.max_per_company
    if cap <= 0 or not key:
        return (True, "")
    if env.company_counts.get(key, 0) >= cap:
        return (False, f"max {cap} contacts per company reached in this run")
    return (True, "")


GATE_FNS: dict[str, GateFn] = {
    "duplicate_in_run": g_duplicate_in_run,
    "email_present": g_email_present,
    "email_blocked": g_email_blocked,
    "blocklist_email": g_blocklist_email,
    "blocklist_domain": g_blocklist_domain,
    "blocklist_company": g_blocklist_company,
    "brand_plausible": g_brand_plausible,
    "not_holding_company": g_not_holding_company,
    "title_gate": g_title_gate,
    "concert_title": g_concert_title,
    "venue_title": g_venue_title,
    "probable_name": g_probable_name,
    "concert_nonprofit_name": g_concert_nonprofit_name,
    "protected_account": g_protected_account,
    "org_name_blocked": g_org_name_blocked,
    "non_sponsor_org_name": g_non_sponsor_org_name,
    "out_of_market_hospital": g_out_of_market_hospital,
    "org_industry_for_brand": g_org_industry_for_brand,
    "sponsor_org_viable": g_sponsor_org_viable,
    "concert_org_viable": g_concert_org_viable,
    "blocklist_name": g_blocklist_name,
    "geo_person_org": g_geo_person_org,
    "title_score_min": g_title_score_min,
    "prospect_score_min": g_prospect_score_min,
    "person_in_florida": g_person_in_florida,
    "max_per_company": g_max_per_company,
}

# chain key -> ordered (stage, gate_id). A preset's gate_chain must be a key here.
CHAINS: dict[str, tuple[tuple[int, str], ...]] = {
    "sponsor": (
        (STAGE_FREE, "duplicate_in_run"),
        (STAGE_FREE, "email_present"),
        (STAGE_FREE, "email_blocked"),
        (STAGE_FREE, "blocklist_email"),
        (STAGE_FREE, "blocklist_domain"),
        (STAGE_FREE, "blocklist_company"),
        (STAGE_FREE, "brand_plausible"),
        (STAGE_FREE, "not_holding_company"),
        (STAGE_FREE, "title_gate"),
        (STAGE_FIRMOGRAPHICS, "org_name_blocked"),
        (STAGE_FIRMOGRAPHICS, "non_sponsor_org_name"),
        (STAGE_FIRMOGRAPHICS, "out_of_market_hospital"),
        (STAGE_FIRMOGRAPHICS, "org_industry_for_brand"),
        (STAGE_FIRMOGRAPHICS, "sponsor_org_viable"),
        (STAGE_POST_ENRICH, "blocklist_name"),
        (STAGE_POST_ENRICH, "geo_person_org"),
        (STAGE_POST_ENRICH, "title_score_min"),
        (STAGE_POST_ENRICH, "prospect_score_min"),
        (STAGE_POST_ENRICH, "max_per_company"),
    ),
    "concert": (
        (STAGE_FREE, "duplicate_in_run"),
        (STAGE_FREE, "email_present"),
        (STAGE_FREE, "email_blocked"),
        (STAGE_FREE, "blocklist_email"),
        (STAGE_FREE, "blocklist_domain"),
        (STAGE_FREE, "blocklist_company"),
        (STAGE_FREE, "protected_account"),
        (STAGE_FREE, "concert_title"),
        (STAGE_FREE, "concert_nonprofit_name"),
        (STAGE_FIRMOGRAPHICS, "concert_org_viable"),
        (STAGE_POST_ENRICH, "blocklist_name"),
        (STAGE_POST_ENRICH, "person_in_florida"),
        (STAGE_POST_ENRICH, "max_per_company"),
    ),
    "venue": (
        (STAGE_FREE, "duplicate_in_run"),
        (STAGE_FREE, "email_present"),
        (STAGE_FREE, "email_blocked"),
        (STAGE_FREE, "blocklist_email"),
        (STAGE_FREE, "blocklist_domain"),
        (STAGE_FREE, "blocklist_company"),
        (STAGE_FREE, "venue_title"),
        (STAGE_POST_ENRICH, "blocklist_name"),
        (STAGE_POST_ENRICH, "person_in_florida"),
        (STAGE_POST_ENRICH, "max_per_company"),
    ),
}


def evaluate_ids(gate_ids: list[str], ctx: LeadCtx, env: GateEnv, *, stage: int) -> list[dict[str, Any]]:
    """Run a named subset of gates. Discovery uses this so email gates wait until after enrich."""
    steps: list[dict[str, Any]] = []
    for gate_id in gate_ids:
        passed, reason = GATE_FNS[gate_id](ctx, env)
        steps.append({"stage": stage, "gate_id": gate_id, "passed": passed, "reason": reason})
    return steps


def evaluate_chain(chain_key: str, ctx: LeadCtx, env: GateEnv) -> list[dict[str, Any]]:
    """Run every gate in the chain and return the trail. Never stops early, so the trail is complete."""
    steps: list[dict[str, Any]] = []
    for stage, gate_id in CHAINS[chain_key]:
        passed, reason = GATE_FNS[gate_id](ctx, env)
        steps.append({"stage": stage, "gate_id": gate_id, "passed": passed, "reason": reason})
    return steps


def state_from_trail(steps: list[dict[str, Any]]) -> str:
    """
    The lead state after the deterministic gates. Blocklist and duplicate failures are "blocked".
    Other failures are "qa_failed" (stages 1 and 3) or "post_qa_failed" (stage 7).
    """
    if all(s["passed"] for s in steps):
        return "needs_review"
    failing = [s for s in steps if not s["passed"]]
    if any(s["gate_id"] in BLOCKED_GATES for s in failing):
        return "blocked"
    if any(s["stage"] < STAGE_POST_ENRICH for s in failing):
        return "qa_failed"
    return "post_qa_failed"


def approvable(lead: dict[str, Any]) -> tuple[bool, str]:
    """
    The one approval rule. The approve endpoint and the push builder both call this.
    A row is approvable only when every deterministic gate passed, the LLM verdict is pass or flag,
    the lead is enriched, and the operator has not rejected it. Returns (ok, reason).
    """
    state = lead.get("state")
    if state == "approved":
        return True, "already approved"
    if state == "pushed":
        return False, "already pushed"
    if state == "rejected":
        return False, "rejected by an operator"
    if state != "needs_review":
        return False, f"lead is {state}, not ready for review"

    for gate in lead.get("gates") or []:
        if not gate.get("passed"):
            return False, f"{gate.get('gate_id')}: {gate.get('reason') or 'failed'}"

    llm = lead.get("llm")
    if not llm:
        return False, "LLM QA missing"
    if llm.get("verdict") not in APPROVABLE_LLM_VERDICTS:
        return False, f"LLM verdict {llm.get('verdict') or 'unknown'}"

    if not (lead.get("person") or {}).get("enriched"):
        return False, "contact not enriched"
    return True, "ok"
