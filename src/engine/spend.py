"""
Spend ceilings and the pre-run estimate.

Slice 1 is cap-based: it turns the operator's caps and toggles into upper
bounds per provider, with no network calls. Lines that depend on survivors
of the free probe report `units=None` ("measured after the free probe").

Ceilings come from env. A provider with spend in the estimate and no ceiling
set blocks Start. Months are calendar months in UTC.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from engine.balances import cursor_window, live_balance, tavily_refresh
from engine.models import (
    Caps,
    Estimate,
    Preset,
    ProviderEstimate,
    SpendLine,
    VerticalSpec,
    toggle_states,
)

if TYPE_CHECKING:
    from engine.store import Store

PROVIDERS: tuple[str, ...] = ("apollo", "tavily", "cursor", "gemini")
PROVIDER_UNIT: dict[str, str] = {"apollo": "credits", "tavily": "credits", "cursor": "runs", "gemini": "requests"}
CEILING_ENV: dict[str, str] = {
    "apollo": "APOLLO_MONTHLY_CREDIT_CEILING",
    "tavily": "TAVILY_MONTHLY_CREDIT_CEILING",
    "cursor": "CURSOR_MONTHLY_RUN_CEILING",
    "gemini": "GEMINI_MONTHLY_REQUEST_CEILING",
}
# Active run statuses hold their reservation until they finish.
ACTIVE_STATUSES = ("queued", "running", "awaiting_enrich", "enriching")
RUN_MAX_TAVILY_QUERIES_DEFAULT = 25


class BudgetStop(RuntimeError):
    """Raised when a paid call would exceed the run's reservation or a monthly ceiling."""

    def __init__(self, provider: str, message: str) -> None:
        super().__init__(message)
        self.provider = provider


class StageGuard(RuntimeError):
    """A paid call was asked for outside the stage that is allowed to make it."""


def utc_month(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def read_ceiling(provider: str) -> float | None:
    """Monthly ceiling from env. Unset, blank, or unparseable means None (paid runs refuse)."""
    raw = os.getenv(CEILING_ENV[provider], "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def run_max_tavily_queries() -> int:
    raw = os.getenv("RUN_MAX_TAVILY_QUERIES", str(RUN_MAX_TAVILY_QUERIES_DEFAULT)).strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return RUN_MAX_TAVILY_QUERIES_DEFAULT


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _ceil_div(n: int, d: int) -> int:
    return 0 if n <= 0 else math.ceil(n / max(1, d))


def cap_lines(
    vertical: VerticalSpec,
    caps: Caps,
    values: dict[str, bool | int | str],
    *,
    brief: str = "",
) -> dict[str, list[SpendLine]]:
    """
    Upper bounds per provider from caps and toggles. Keys are providers; lines with
    units=None are unknown until the free probe runs (slice 3).
    """
    lines: dict[str, list[SpendLine]] = {p: [] for p in PROVIDERS}

    if vertical.source.kind == "research_events":
        sources = caps.events
        per_source = caps.queries_per_source
        brands = caps.brands
        per_company = int(values.get("max_per_company", 2) or 0)

        tavily_calls = min(sources * per_source, run_max_tavily_queries())
        lines["tavily"].append(
            SpendLine(
                label="Brand searches",
                units=float(tavily_calls),
                note="repeats are free",
            )
        )
        if values.get("discover_new_events") is True:
            discover = _env_int("MIAMI_EVENTS_TAVILY_QUERIES", 8)
            lines["tavily"].append(SpendLine(label="Discover new events", units=float(discover)))
            lines["cursor"].append(SpendLine(label="Discover new events", units=1.0))

        if brief.strip():
            used = int(sum(line.units or 0 for line in lines["tavily"]))
            extra = min(sources, max(0, run_max_tavily_queries() - used))
            if extra:
                lines["tavily"].append(
                    SpendLine(label="Searches for your brief", units=float(extra), note="inside this run's cap")
                )

        score_batch = _env_int("CURSOR_SCORE_BATCH_SIZE", 6)
        lines["cursor"].append(SpendLine(label="Reading each source", units=float(sources)))
        lines["cursor"].append(SpendLine(label="Scoring brands", units=float(_ceil_div(brands, score_batch))))
        lines["cursor"].append(SpendLine(label="Matching the employer", units=1.0))

        lines["apollo"].append(SpendLine(label="Company lookups", units=float(brands * 3), note="up to 3 per brand"))
        lines["apollo"].append(
            SpendLine(label="People to enrich", units=float(brands * per_company), note="after you confirm the shortlist")
        )
        return lines

    # Apollo people verticals (Concert Series, Venue rental)
    target = caps.target
    batch = max(1, caps.tavily_batch)
    use_org_path = values.get("org_path") is True
    if use_org_path:
        lines["apollo"].append(
            SpendLine(label="Company search pages", units=float(caps.org_pages), note="1 credit per page")
        )
    lines["apollo"].append(
        SpendLine(
            label="Company lookups",
            units=None,
            note="filled in when you measure",
        )
    )
    lines["apollo"].append(
        SpendLine(label="People to enrich", units=float(target), note="after you confirm the shortlist")
    )

    if vertical.id == "concert_series" and values.get("require_spend_evidence") is True:
        searches = min(_ceil_div(target, batch), run_max_tavily_queries())
        lines["tavily"].append(SpendLine(label="Sponsorship searches", units=float(searches)))
    gemini_batches = _ceil_div(target, max(1, _env_int("GEMINI_QA_BATCH_SIZE", caps.gemini_batch)))
    lines["gemini"].append(
        SpendLine(label="Quality check", units=float(gemini_batches), note="until you measure")
    )
    return lines


def _remaining(
    store: "Store",
    provider: str,
    *,
    total: float | None,
    mtd: float,
    reserved: float,
    ceiling: float | None,
    now: datetime | None,
) -> tuple[float | None, str | None, str | None]:
    """Remaining credits, the refresh date, and a start blocker. Gemini has no balance."""
    needed = float(total or 0)
    if provider == "gemini":
        return None, None, None
    if provider == "cursor":
        start, end = cursor_window(now)
        spent = store.ledger_between(provider, start.isoformat(), end.isoformat())
        if ceiling is None:
            blocker = f"{CEILING_ENV[provider]} is not set, so paid {provider} runs are refused." if needed > 0 else None
            return None, end.date().isoformat(), blocker
        left = ceiling - spent - reserved
        blocker = None
        if needed > 0 and needed > left:
            blocker = (
                f"{provider}: {spent:g} used this cycle + {reserved:g} reserved + this run {needed:g} "
                f"exceeds the {ceiling:g} ceiling."
            )
        return left, end.date().isoformat(), blocker

    live = live_balance(store, provider)
    if live is not None:
        left = float(live["remaining"]) - reserved
        refreshes = str(live.get("refreshes_on") or "") or None
        blocker = None
        if needed > 0 and needed > left:
            blocker = f"Not enough {provider} credits left for this run."
        return left, refreshes, blocker

    if provider == "tavily":
        refreshes: str | None = tavily_refresh(now)
    else:
        refreshes = None
    if ceiling is None:
        blocker = f"{CEILING_ENV[provider]} is not set, so paid {provider} runs are refused." if needed > 0 else None
        return None, refreshes, blocker
    left = ceiling - mtd - reserved
    blocker = None
    if needed > 0 and mtd + reserved + needed > ceiling:
        blocker = (
            f"{provider}: month-to-date {mtd:g} + reserved {reserved:g} + this run {needed:g} "
            f"exceeds the {ceiling:g} ceiling."
        )
    return left, refreshes, blocker


def _sum_known(lines: list[SpendLine]) -> float | None:
    """Sum of the lines with known units. Unknown lines are excluded and flagged in their note."""
    known = [line.units for line in lines if line.units is not None]
    return float(sum(known)) if known else None


def month_to_date(store: "Store", provider: str, now: datetime | None = None) -> float:
    return store.ledger_total(provider, utc_month(now))


def reserved_by_active_runs(store: "Store", provider: str) -> float:
    return store.reserved_total(provider)


def enrich_reservation(companies: list[str], *, target: int, max_per_company: int) -> int:
    """How many contacts this list can enrich, after the per-company cap and the target."""
    counts: dict[str, int] = {}
    kept = 0
    for company in companies:
        if target > 0 and kept >= target:
            break
        if max_per_company > 0 and counts.get(company, 0) >= max_per_company:
            continue
        counts[company] = counts.get(company, 0) + 1
        kept += 1
    return kept


def apply_measured_counts(
    lines: dict[str, list[SpendLine]],
    probe: dict[str, Any],
    vertical: VerticalSpec,
    values: dict[str, bool | int | str],
    caps: Caps,
) -> dict[str, list[SpendLine]]:
    """Replace free-probe placeholders with counts from stages 0 and 1."""
    max_per = int(values.get("max_per_company") or 0)
    org_path = values.get("org_path") is True
    companies = list(probe.get("companies") or [])
    if org_path:
        enrich_n = float(caps.target)
    else:
        enrich_n = float(enrich_reservation(companies, target=caps.target, max_per_company=max_per))
    org_n = 0.0 if vertical.id == "venue_rental" else float(probe.get("uncached_orgs") or 0)
    spend_n = float(min(_ceil_div(int(probe.get("uncached_spend_brands") or 0), max(1, caps.tavily_batch)), run_max_tavily_queries()))
    gemini_n = float(_ceil_div(int(probe.get("survivors") or 0), max(1, _env_int("GEMINI_QA_BATCH_SIZE", caps.gemini_batch))))
    out: dict[str, list[SpendLine]] = {}
    for provider, provider_lines in lines.items():
        updated: list[SpendLine] = []
        for line in provider_lines:
            label = line.label
            if label == "Company lookups":
                note = "Venue skips this" if vertical.id == "venue_rental" else "companies not looked up before"
                updated.append(SpendLine(label=label, units=org_n, note=note))
            elif label == "People to enrich":
                note = "uses the lead target" if org_path else "people who passed the free checks"
                updated.append(SpendLine(label=label, units=enrich_n, note=note))
            elif label == "Sponsorship searches":
                updated.append(SpendLine(label=label, units=spend_n, note="brands not checked before"))
            elif label == "Quality check":
                updated.append(SpendLine(label=label, units=gemini_n, note="one check per batch"))
            else:
                updated.append(line)
        out[provider] = updated
    return out


def probe_cache_key(vertical_id: str, values: dict[str, Any], caps: Caps) -> str:
    blob = json.dumps({"vertical": vertical_id, "toggles": values, "caps": caps.model_dump()}, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()


def build_estimate(
    store: "Store",
    preset: Preset,
    vertical: VerticalSpec,
    values: dict[str, bool | int | str],
    caps: Caps,
    *,
    now: datetime | None = None,
    probe: dict[str, Any] | None = None,
    brief: str = "",
) -> Estimate:
    lines = cap_lines(vertical, caps, values, brief=brief)
    if probe is not None and vertical.source.kind == "apollo_people":
        lines = apply_measured_counts(lines, probe, vertical, values, caps)
    blockers: list[str] = []
    providers: list[ProviderEstimate] = []
    for provider in PROVIDERS:
        provider_lines = lines[provider]
        if not provider_lines:
            continue
        total = _sum_known(provider_lines)
        mtd = month_to_date(store, provider, now)
        reserved = reserved_by_active_runs(store, provider)
        ceiling = read_ceiling(provider)
        remaining, refreshes_on, blocker = _remaining(
            store, provider, total=total, mtd=mtd, reserved=reserved, ceiling=ceiling, now=now,
        )
        if blocker:
            blockers.append(blocker)
        providers.append(
            ProviderEstimate(
                provider=provider,
                unit=PROVIDER_UNIT[provider],
                lines=provider_lines,
                total=total,
                month_to_date=mtd,
                reserved=reserved,
                ceiling=ceiling,
                remaining=remaining,
                refreshes_on=refreshes_on,
                blocker=blocker,
            )
        )

    return Estimate(
        preset_id=preset.id,
        vertical_id=vertical.id,
        toggles=toggle_states(vertical, values),
        providers=providers,
        blockers=blockers,
        can_start=not blockers,
        note=(
            "Free people search has been measured."
            if probe is not None
            else "Upper bounds. Press Measure to fill in the lines that are still unknown."
        ),
    )


def cache_ttl_days() -> int:
    raw = os.getenv("API_CACHE_TTL_DAYS", "30").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 30


def cache_digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(raw.encode()).hexdigest()


def cache_fresh(store: "Store", provider: str, op: str, key: str) -> Any | None:
    """Return a cached payload, or None when it is missing or older than API_CACHE_TTL_DAYS."""
    row = store.cache_get(provider, op, key)
    if row is None:
        return None
    fetched = datetime.fromisoformat(str(row["fetched_at"]))
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - fetched > timedelta(days=cache_ttl_days()):
        return None
    return row["payload"]


class Meter:
    """
    One run's paid calls. Cache hits cost 0. A call outside its stage raises StageGuard.
    enrich() also requires the run status to be enriching, so a shortlist pause cannot spend.
    """

    def __init__(self, store: "Store", run_id: str, stage: str) -> None:
        self.store = store
        self.run_id = run_id
        self.stage = stage

    def _require(self, *allowed: str) -> None:
        if self.stage not in allowed:
            raise StageGuard(f"stage {self.stage} cannot make a {allowed[0]} call")

    def _can_charge(self, provider: str, units: float) -> None:
        if units <= 0:
            return
        run = self.store.get_run(self.run_id) or {}
        spent = self.store.ledger_run_total(self.run_id, provider)
        reserved = float((run.get("reservation") or {}).get(provider) or 0)
        if spent + units > reserved + 1e-9:
            raise BudgetStop(
                provider,
                f"{provider}: this call ({units:g}) would pass the {reserved:g} reservation (spent {spent:g}).",
            )
        if provider == "gemini" and read_ceiling(provider) is None:
            return
        ceiling = read_ceiling(provider)
        if ceiling is None:
            live = live_balance(self.store, provider)
            left = None if live is None else float(live["remaining"])
            if left is None:
                raise BudgetStop(provider, f"{CEILING_ENV[provider]} is not set.")
            if units > left + 1e-9:
                raise BudgetStop(provider, f"{provider}: this call ({units:g}) is more than the {left:g} credits left.")
            return
        mtd = month_to_date(self.store, provider)
        if mtd + units > ceiling + 1e-9:
            raise BudgetStop(provider, f"{provider}: month-to-date {mtd:g} + {units:g} exceeds the {ceiling:g} ceiling.")

    def _commit(self, provider: str, units: float, stage: str) -> None:
        if units <= 0:
            return
        self.store.ledger_append(
            provider=provider, units=units, month=utc_month(), run_id=self.run_id, stage=stage, kind="actual"
        )

    def people_search(self, apollo: Any, payload: dict[str, Any]) -> dict[str, Any]:
        """Free people search. Allowed during source, the org-keyword path, and research enrich."""
        self._require("source", "org", "enrich")
        key = cache_digest(payload)
        hit = cache_fresh(self.store, "apollo", "people", key)
        if isinstance(hit, dict):
            return hit
        data = apollo.search_people(payload, page=int(payload.get("page") or 1))
        if not data:
            raise RuntimeError("Apollo people search returned nothing.")
        self.store.cache_put("apollo", "people", key, data, 0)
        return data

    def org_lookup(self, apollo: Any, *, domain: str, company: str) -> tuple[dict[str, Any], float]:
        """One organization page. 1 credit on a miss, 0 on a hit. Returns (org, units charged)."""
        self._require("org")
        from prospecting_qa import normalize_company_key, website_domain_key

        domain_key = website_domain_key(domain)
        ident = f"dom:{domain_key}" if domain_key else f"name:{normalize_company_key(company)}"
        hit = cache_fresh(self.store, "apollo", "org", ident)
        if isinstance(hit, dict):
            return hit, 0.0
        self._can_charge("apollo", 1)
        if domain_key:
            data = apollo.search_organization_by_domain(domain_key)
        else:
            data = apollo.search_organization_by_name(company)
        if data is None:
            raise RuntimeError(f"Apollo org lookup returned nothing for {company or domain_key}.")
        from apollo_client import ApolloClient

        orgs = ApolloClient.orgs_from_search_response(data)
        org = orgs[0] if orgs else {}
        self._commit("apollo", 1, "org")
        self.store.cache_put("apollo", "org", ident, org, 1)
        return org, 1.0

    def org_keyword_page(self, apollo: Any, payload: dict[str, Any]) -> dict[str, Any]:
        """Org-keyword search page. 1 credit per page on a miss."""
        self._require("org")
        key = "page:" + cache_digest(payload)
        hit = cache_fresh(self.store, "apollo", "orgpage", key)
        if isinstance(hit, dict):
            return hit
        self._can_charge("apollo", 1)
        data = apollo.search_companies(dict(payload), page=int(payload.get("page") or 1))
        if data is None:
            raise RuntimeError("Apollo org-keyword search returned nothing.")
        self._commit("apollo", 1, "org")
        self.store.cache_put("apollo", "orgpage", key, data, 1)
        return data

    def tavily_queries_used(self) -> float:
        return self.store.ledger_run_total(self.run_id, "tavily")

    def charge_tavily(self, units: float) -> None:
        self._require("spend")
        self._charge_tavily(units, "spend")

    def charge_source_tavily(self, units: float) -> None:
        """Research-lane searches. Same run cap and ledger as spend evidence."""
        self._require("source")
        self._charge_tavily(units, "source")

    def _charge_tavily(self, units: float, stage: str) -> None:
        if units <= 0:
            return
        if self.tavily_queries_used() + units > run_max_tavily_queries() + 1e-9:
            raise BudgetStop("tavily", f"Tavily would pass the {run_max_tavily_queries()} search cap for this run.")
        self._can_charge("tavily", units)
        self._commit("tavily", units, stage)

    def charge_cursor(self, units: float = 1) -> None:
        """One Cursor run unit per extract, score batch, employer resolve, or event discovery."""
        self._require("source", "llm")
        if units <= 0:
            return
        self._can_charge("cursor", units)
        self._commit("cursor", units, self.stage)

    def remember_spend(self, company_key: str, payload: dict[str, Any]) -> None:
        self.store.cache_put("tavily", "spend", company_key, payload, 0)

    def spend_hit(self, company_key: str) -> dict[str, Any] | None:
        hit = cache_fresh(self.store, "tavily", "spend", company_key)
        return hit if isinstance(hit, dict) else None

    def gemini_hit(self, key: str) -> dict[str, Any] | None:
        hit = cache_fresh(self.store, "gemini", "qa", key)
        return hit if isinstance(hit, dict) else None

    def charge_gemini(self) -> None:
        self._require("llm")
        self._can_charge("gemini", 1)
        self._commit("gemini", 1, "llm")

    def remember_gemini(self, key: str, verdict: dict[str, Any]) -> None:
        self.store.cache_put("gemini", "qa", key, verdict, 1)

    def enrich(self, apollo: Any, person_id: str) -> tuple[dict[str, Any], float]:
        """People match. Refuses unless the run is enriching. 1 credit on a miss."""
        run = self.store.get_run(self.run_id)
        if not run or run.get("status") != "enriching":
            raise StageGuard("enrich only runs while the run is enriching")
        self._require("enrich")
        key = str(person_id)
        hit = cache_fresh(self.store, "apollo", "person", key)
        if isinstance(hit, dict):
            return hit, 0.0
        self._can_charge("apollo", 1)
        person = apollo.enrich_person(person_id)
        if not person:
            raise RuntimeError(f"Apollo enrich returned nothing for {person_id}.")
        self._commit("apollo", 1, "enrich")
        self.store.cache_put("apollo", "person", key, person, 1)
        return person, 1.0
