"""
Concert and Venue discovery.

Stage 0 is free Apollo people search. Free gates run before any credit is spent.
Concert then buys org lookups, firmographic gates, and Tavily spend evidence.
Both lanes pause for a shortlist review, then enrich only the leads still shortlisted.
Venue skips org lookup, firmographics, and Tavily.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from concert_series_config import concert_employee_ranges
from concert_series_qa import concert_org_name, concert_org_viable, contact_location
from concert_series_spend import (
    SPEND_AMBIGUOUS,
    SPEND_PASS,
    company_spend_key,
    evidence_from_tavily_response,
    spend_search_query_batch,
)
from engine.crm import ensure_snapshot, load_blocklist
from engine.gates import (
    STAGE_FIRMOGRAPHICS,
    STAGE_FREE,
    STAGE_POST_ENRICH,
    GateEnv,
    LeadCtx,
    evaluate_ids,
    state_from_trail,
)
from engine.models import resolve_caps, resolve_toggle_values
from engine.presets import get_preset
from engine.spend import BudgetStop, Meter, cache_fresh
from prospecting_qa import normalize_company_key, normalize_email, website_domain_key
from venue_rental_config import VENUE_RENTAL_ORG_EMPLOYEE_RANGES
from venue_rental_qa import normalize_person_id

SearchFn = Callable[[str], dict[str, Any]]

CONCERT_PRE_ORG = [
    "concert_title",
    "blocklist_company",
    "blocklist_domain",
    "probable_name",
    "concert_nonprofit_name",
    "protected_account",
]
VENUE_PRE_ORG = ["venue_title", "blocklist_company", "blocklist_domain", "probable_name"]
POST_ENRICH = [
    "email_present",
    "email_blocked",
    "blocklist_email",
    "blocklist_name",
    "person_in_florida",
    "max_per_company",
]


def default_apollo() -> Any:
    key = os.getenv("APOLLO_API_KEY", "").strip()
    if not key:
        raise RuntimeError("APOLLO_API_KEY is not set")
    from apollo_client import ApolloClient

    return ApolloClient(key)


def default_tavily(query: str) -> dict[str, Any]:
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("TAVILY_API_KEY is not set")
    from tavily import TavilyClient

    from concert_series_spend import _search_kwargs

    return TavilyClient(api_key=key).search(query=query, **_search_kwargs()) or {}


apollo_factory = default_apollo
tavily_factory: SearchFn = default_tavily


def _people_of(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not data:
        return []
    for key in ("people", "contacts"):
        rows = data.get(key)
        if isinstance(rows, list):
            return rows
    return []


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    size = max(1, size)
    return [items[i : i + size] for i in range(0, len(items), size)] or [[]]


def _tiers_from_params(params: dict[str, Any]) -> list[tuple[int, list[str]]]:
    tiers: list[tuple[int, list[str]]] = []
    for row in params.get("person_location_tiers") or []:
        if not isinstance(row, dict):
            continue
        locations = [str(item).strip() for item in (row.get("locations") or []) if str(item).strip()]
        tiers.append((int(row.get("tier") or 0), locations))
    return tiers


def _locations(vertical_id: str, values: dict[str, Any], tiers: list[tuple[int, list[str]]]) -> list[tuple[int, list[str]]]:
    if vertical_id == "venue_rental":
        if values.get("us_fallback"):
            return [tiers[-1]] if tiers else []
        return [tier for tier in tiers if tier[0] <= 3]
    max_tier = int(values.get("max_tier") or 3)
    return [tier for tier in tiers if tier[0] <= max_tier]


def _people_payload(
    *,
    page: int,
    titles: list[str],
    seniorities: list[str],
    locations: list[str] | None,
    include_similar: bool,
    revenue_min: int | None,
    employee_ranges: list[str] | None,
    organization_ids: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "page": page,
        "per_page": 100,
        "person_titles": titles,
        "person_seniorities": seniorities,
        "include_similar_titles": include_similar,
        "contact_email_status": ["verified"],
    }
    if locations:
        payload["person_locations"] = locations
    if revenue_min and revenue_min > 0:
        payload["revenue_range[min]"] = int(revenue_min)
    if employee_ranges:
        payload["organization_num_employees_ranges"] = list(employee_ranges)
    if organization_ids:
        payload["organization_ids"] = organization_ids
    return payload


def _org_blob(person: dict[str, Any], enriched: dict[str, Any] | None = None) -> dict[str, Any]:
    base = person.get("organization") or {}
    extra = (enriched or {}).get("organization") or {}
    org = {**base, **{k: v for k, v in extra.items() if v not in (None, "")}}
    return {
        "name": concert_org_name(person, enriched),
        "website_url": org.get("website_url") or "",
        "primary_domain": org.get("primary_domain") or org.get("website_url") or "",
        "industry": org.get("industry") or "",
        "annual_revenue": org.get("annual_revenue"),
        "estimated_num_employees": org.get("estimated_num_employees") or org.get("num_employees"),
        "city": org.get("city") or "",
        "state": org.get("state") or "",
        "country": org.get("country") or "",
    }


def _ctx(person: dict[str, Any], vertical_label: str, enriched: dict[str, Any] | None = None) -> LeadCtx:
    enriched = enriched or {}
    org = _org_blob(person, enriched)
    city, state, country = contact_location(person, enriched or None)
    email = normalize_email(enriched.get("email") or person.get("email") or "")
    first = (enriched.get("first_name") or person.get("first_name") or "").strip()
    last = (enriched.get("last_name") or person.get("last_name") or person.get("last_name_obfuscated") or "").strip()
    return LeadCtx(
        vertical_label=vertical_label,
        shelf_brand=org["name"],
        company=org["name"],
        first=first,
        last=last,
        title=(enriched.get("title") or person.get("title") or "").strip(),
        email=email,
        website=website_domain_key(org["primary_domain"]),
        industry=str(org["industry"] or ""),
        annual_revenue=org["annual_revenue"],
        employees=org["estimated_num_employees"],
        city=city,
        state=state,
        country=country,
        org_city=org["city"],
        org_state=org["state"],
        org_country=org["country"],
    )


def _person_json(person: dict[str, Any], ctx: LeadCtx, *, enriched: bool, apollo_id: str) -> dict[str, Any]:
    return {
        "enriched": enriched,
        "apollo_id": apollo_id,
        "first_name": ctx.first,
        "last_name": ctx.last,
        "title": ctx.title,
        "city": ctx.city,
        "state": ctx.state,
        "country": ctx.country,
        "organization": _org_blob(person),
    }


def _lead_columns(ctx: LeadCtx, monday_vertical: str) -> dict[str, Any]:
    location = ", ".join(part for part in (ctx.city, ctx.state, ctx.country) if part)
    return {
        "shelf_brand": ctx.shelf_brand,
        "person_name": f"{ctx.first} {ctx.last}".strip(),
        "title": ctx.title,
        "email": ctx.email,
        "domain": ctx.email_domain or ctx.website,
        "location": location,
        "vertical": monday_vertical,
    }


def _ctx_from_lead(lead: dict[str, Any]) -> LeadCtx:
    person = lead.get("person") or {}
    org = person.get("organization") or {}
    return LeadCtx(
        vertical_label=lead.get("vertical") or "",
        shelf_brand=lead.get("shelf_brand") or org.get("name") or "",
        company=org.get("name") or lead.get("shelf_brand") or "",
        first=person.get("first_name") or "",
        last=person.get("last_name") or "",
        title=lead.get("title") or "",
        email=lead.get("email") or "",
        website=website_domain_key(org.get("primary_domain") or org.get("website_url") or ""),
        industry=str(org.get("industry") or ""),
        annual_revenue=org.get("annual_revenue"),
        employees=org.get("estimated_num_employees"),
        city=person.get("city") or "",
        state=person.get("state") or "",
        country=person.get("country") or "",
        org_city=org.get("city") or "",
        org_state=org.get("state") or "",
        org_country=org.get("country") or "",
    )


def _merge_gates(existing: list[dict[str, Any]], steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = {step["gate_id"] for step in steps}
    return [gate for gate in existing if gate["gate_id"] not in ids] + steps


def _pre_state(steps: list[dict[str, Any]]) -> str:
    state = state_from_trail(steps)
    return "candidate" if state == "needs_review" else state


def _halt(store: Any, run_id: str) -> bool:
    run = store.get_run(run_id)
    if run and run.get("cancel_requested"):
        store.set_status(run_id, "cancelled", stage_name="Cancelled")
        store.add_event(run_id, "info", "Cancelled")
        return True
    return False


def _checkpoint(store: Any, run_id: str, stage: int, status: str = "running") -> None:
    from engine.pipeline import STAGE_NAMES

    store.set_status(run_id, status, stage=stage, stage_name=STAGE_NAMES.get(stage, ""))


def _known_ids(store: Any, run_id: str) -> set[str]:
    found: set[str] = set()
    for lead in store.list_leads(run_id):
        apollo_id = (lead.get("person") or {}).get("apollo_id")
        if apollo_id:
            found.add(str(apollo_id))
    return found


def _candidates(store: Any, run_id: str) -> list[dict[str, Any]]:
    return [lead for lead in store.list_leads(run_id) if lead["state"] == "candidate"]


def import_legacy_spend_cache(store: Any) -> int:
    """Copy concert_spend_cache.json into the API cache once. Later reads are free."""
    if cache_fresh(store, "tavily", "import", "concert_spend_json") is not None:
        return 0
    from concert_series_config import concert_spend_cache_path

    imported = 0
    path = concert_spend_cache_path()
    if path and os.path.isfile(path):
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        entries = raw.get("entries") if isinstance(raw, dict) and int(raw.get("_version") or 0) == 2 else {}
        if isinstance(entries, dict):
            for key, row in entries.items():
                if key and isinstance(row, dict):
                    store.cache_put("tavily", "spend", str(key), row, 0)
                    imported += 1
    store.cache_put("tavily", "import", "concert_spend_json", {"imported": imported}, 0)
    return imported


def _gate_person(
    store: Any,
    run_id: str,
    person: dict[str, Any],
    *,
    vertical_id: str,
    label: str,
    blocklist: Any,
    values: dict[str, Any],
    known: set[str],
) -> str | None:
    """Insert one searched person. Returns 'stop' when the target is already met by the caller."""
    apollo_id = normalize_person_id(person)
    if not apollo_id or apollo_id in known:
        return None
    known.add(apollo_id)
    ctx = _ctx(person, label)
    gate_ids = CONCERT_PRE_ORG if vertical_id == "concert_series" else VENUE_PRE_ORG
    env = GateEnv(blocklist=blocklist, toggles=values, max_per_company=int(values.get("max_per_company") or 0))
    steps = evaluate_ids(gate_ids, ctx, env, stage=STAGE_FREE)
    state = _pre_state(steps)
    store.insert_lead(
        run_id,
        state,
        gates=steps,
        person=_person_json(person, ctx, enriched=False, apollo_id=apollo_id),
        **_lead_columns(ctx, label),
    )
    return state


def _search_people(
    store: Any,
    meter: Meter,
    apollo: Any,
    *,
    run_id: str,
    vertical_id: str,
    label: str,
    values: dict[str, Any],
    caps: Any,
    blocklist: Any,
    titles: list[str],
    seniorities: list[str],
    tiers: list[tuple[int, list[str]]],
    organization_ids: list[str] | None = None,
) -> None:
    known = _known_ids(store, run_id)
    target = max(0, int(caps.target))
    concert = vertical_id == "concert_series"
    revenue = int(values.get("min_revenue") or 0) if concert else None
    ranges = concert_employee_ranges(int(values.get("min_employees") or 0)) if concert else None
    include_similar = not concert
    if organization_ids:
        location_sets: list[list[str] | None] = [None]
    else:
        location_sets = [locs for _tier, locs in _locations(vertical_id, values, tiers)]
    title_groups = _chunks(list(titles), int(caps.title_chunk))
    max_pages = 2 if organization_ids else int(caps.max_pages)

    def _one(locations: list[str] | None, org_ids: list[str] | None, title_group: list[str]) -> bool:
        for page in range(1, max_pages + 1):
            if _halt(store, run_id):
                return True
            payload = _people_payload(
                page=page,
                titles=title_group,
                seniorities=list(seniorities),
                locations=locations,
                include_similar=include_similar,
                revenue_min=None if organization_ids else revenue,
                employee_ranges=None if organization_ids else ranges,
                organization_ids=org_ids,
            )
            data = meter.people_search(apollo, payload)
            for person in _people_of(data):
                _gate_person(
                    store, run_id, person,
                    vertical_id=vertical_id, label=label, blocklist=blocklist, values=values, known=known,
                )
                if store.count_leads(run_id).get("candidate", 0) >= target:
                    return True
            total_pages = int((data.get("pagination") or {}).get("total_pages") or page)
            if page >= total_pages or not _people_of(data):
                break
        return store.count_leads(run_id).get("candidate", 0) >= target

    if organization_ids:
        for oid in organization_ids:
            if _one(None, [oid], list(titles)):
                return
        return
    for locations in location_sets:
        for title_group in title_groups:
            if _one(locations, None, title_group):
                return


def _org_keyword_people(store: Any, apollo: Any, run: dict[str, Any], vertical: Any, values: dict[str, Any], caps: Any, blocklist: Any, label: str) -> None:
    if values.get("org_path") is not True:
        return
    if store.count_leads(run["id"]).get("candidate", 0) >= int(caps.target):
        return
    meter = Meter(store, run["id"], "org")
    concert = vertical.id == "concert_series"
    ranges = concert_employee_ranges(int(values.get("min_employees") or 0)) if concert else list(VENUE_RENTAL_ORG_EMPLOYEE_RANGES)
    revenue = int(values.get("min_revenue") or 0) if concert else None
    params = vertical.source.params
    org_ids: list[str] = []
    for page in range(1, int(caps.org_pages) + 1):
        if _halt(store, run["id"]):
            return
        payload: dict[str, Any] = {
            "page": page,
            "per_page": 100,
            "q_organization_keyword_tags": list(params.get("org_keyword_tags") or []),
            "organization_locations": list(params.get("org_locations") or []),
            "organization_num_employees_ranges": ranges,
        }
        if revenue and revenue > 0:
            payload["revenue_range[min]"] = revenue
        data = meter.org_keyword_page(apollo, payload)
        from apollo_client import ApolloClient

        for org in ApolloClient.orgs_from_search_response(data):
            oid = org.get("id") or org.get("organization_id")
            if oid:
                org_ids.append(str(oid))
        total_pages = int((data.get("pagination") or {}).get("total_pages") or page)
        if page >= total_pages:
            break
    if not org_ids:
        return
    people_meter = Meter(store, run["id"], "org")
    _search_people(
        store, people_meter, apollo, run_id=run["id"], vertical_id=vertical.id, label=label, values=values,
        caps=caps, blocklist=blocklist, titles=list(params.get("titles") or []),
        seniorities=list(params.get("seniorities") or []), tiers=_tiers_from_params(params),
        organization_ids=org_ids,
    )


def _known_bad_org_reason(lead: dict[str, Any], values: dict[str, Any]) -> str | None:
    """A company the free Apollo record already rules out. Unknown industry still needs a paid lookup."""
    ctx = _ctx_from_lead(lead)
    ok, reason = concert_org_viable(
        org_name=ctx.org_name,
        org_industry=ctx.industry,
        email=ctx.email,
        annual_revenue=ctx.annual_revenue,
        estimated_employees=ctx.employees,
        min_revenue=int(values.get("min_revenue") or 10_000_000),
        min_employees=int(values.get("min_employees") or 51),
        strict=True,
    )
    if ok or not reason or "unknown" in reason:
        return None
    return reason


def _reject_known_bad_orgs(store: Any, run_id: str, values: dict[str, Any]) -> None:
    seen: set[str] = set()
    for lead in list(_candidates(store, run_id)):
        org = (lead.get("person") or {}).get("organization") or {}
        key = normalize_company_key(org.get("name") or lead.get("shelf_brand") or "")
        if not key or key in seen:
            continue
        reason = _known_bad_org_reason(lead, values)
        if not reason:
            continue
        seen.add(key)
        step = {"stage": STAGE_FIRMOGRAPHICS, "gate_id": "concert_org_viable", "passed": False, "reason": reason}
        for sibling in list(_candidates(store, run_id)):
            sibling_org = (sibling.get("person") or {}).get("organization") or {}
            sibling_key = normalize_company_key(sibling_org.get("name") or sibling.get("shelf_brand") or "")
            if sibling_key != key:
                continue
            gates = _merge_gates(sibling.get("gates") or [], [step])
            store.update_lead(sibling["id"], gates=gates, state=_pre_state(gates))


def _lookup_orgs(store: Any, apollo: Any, run_id: str) -> None:
    meter = Meter(store, run_id, "org")
    seen: set[str] = set()
    for lead in _candidates(store, run_id):
        org = (lead.get("person") or {}).get("organization") or {}
        key = normalize_company_key(org.get("name") or lead.get("shelf_brand") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        domain = org.get("primary_domain") or org.get("website_url") or ""
        found, charged = meter.org_lookup(apollo, domain=domain, company=org.get("name") or lead["shelf_brand"])
        if not found:
            continue
        for sibling in _candidates(store, run_id):
            sibling_org = (sibling.get("person") or {}).get("organization") or {}
            if normalize_company_key(sibling_org.get("name") or sibling.get("shelf_brand") or "") != key:
                continue
            person = dict(sibling["person"])
            merged = dict(sibling_org)
            for field, value in found.items():
                if value not in (None, ""):
                    merged[field] = value
            if found.get("name"):
                merged["name"] = found["name"]
            person["organization"] = merged
            cost = float(sibling.get("cost_spent") or 0) + (charged if sibling["id"] == lead["id"] else 0)
            columns = _lead_columns(_ctx_from_lead({**sibling, "person": person}), sibling["vertical"])
            store.update_lead(sibling["id"], person=person, cost_spent=cost, **columns)


def _firmographics(store: Any, run_id: str, values: dict[str, Any], blocklist: Any) -> None:
    env = GateEnv(blocklist=blocklist, toggles=values, max_per_company=int(values.get("max_per_company") or 0))
    for lead in _candidates(store, run_id):
        steps = evaluate_ids(["concert_org_viable"], _ctx_from_lead(lead), env, stage=STAGE_FIRMOGRAPHICS)
        gates = _merge_gates(lead.get("gates") or [], steps)
        state = _pre_state(gates)
        store.update_lead(lead["id"], gates=gates, state=state)


def _apply_spend_payload(store: Any, lead: dict[str, Any], payload: dict[str, Any]) -> None:
    passed = payload.get("verdict") == SPEND_PASS
    reason = str(payload.get("reason") or "")
    if not passed and not reason:
        reason = str(payload.get("verdict") or "no paid spend evidence")
    step = {"stage": 4, "gate_id": "spend_evidence", "passed": passed, "reason": "" if passed and reason == "pass" else reason}
    gates = _merge_gates(lead.get("gates") or [], [step])
    evidence = list(lead.get("evidence") or [])
    notes = str(payload.get("notes") or "").strip()
    if notes and notes not in evidence:
        evidence.append(notes)
    store.update_lead(lead["id"], gates=gates, state=_pre_state(gates), evidence=evidence)


def _spend(store: Any, run: dict[str, Any], values: dict[str, Any], caps: Any) -> None:
    if values.get("require_spend_evidence") is not True:
        for lead in _candidates(store, run["id"]):
            _apply_spend_payload(store, lead, {"verdict": SPEND_PASS, "reason": "spend evidence off"})
        return
    imported = import_legacy_spend_cache(store)
    if imported:
        store.add_event(run["id"], "info", f"Imported {imported} cached spend result(s)")
    meter = Meter(store, run["id"], "spend")
    by_key: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for lead in _candidates(store, run["id"]):
        name = lead.get("shelf_brand") or ""
        key = company_spend_key(name)
        if not key:
            _apply_spend_payload(store, lead, {"verdict": SPEND_AMBIGUOUS, "reason": "empty_company"})
            continue
        by_key.setdefault(key, []).append((name, lead))
        if key not in order:
            order.append(key)
    needed: list[str] = []
    for key in order:
        cached = meter.spend_hit(key)
        name, _lead = by_key[key][0]
        if cached is not None:
            for _name, lead in by_key[key]:
                fresh = store.get_lead(lead["id"]) or lead
                _apply_spend_payload(store, fresh, cached)
            continue
        needed.append(name)
    batch = max(1, int(caps.tavily_batch))
    for group in _chunks(needed, batch):
        query = spend_search_query_batch(group)
        meter.charge_tavily(1)
        response = tavily_factory(query)
        found = evidence_from_tavily_response(group, response, query)
        for name in group:
            key = company_spend_key(name)
            evidence = found.get(key)
            payload = evidence.to_disk() if evidence is not None else {"verdict": SPEND_AMBIGUOUS, "reason": "batch_miss", "notes": "", "query": query}
            meter.remember_spend(key, payload)
            for _name, lead in by_key.get(key, []):
                fresh = store.get_lead(lead["id"]) or lead
                _apply_spend_payload(store, fresh, payload)


def _enrich(store: Any, apollo: Any, run: dict[str, Any], values: dict[str, Any], blocklist: Any) -> str:
    _checkpoint(store, run["id"], 6, "enriching")
    meter = Meter(store, run["id"], "enrich")
    cap = int(values.get("max_per_company") or 0)
    counts: dict[str, int] = {}
    enriched = 0
    for lead in [item for item in store.list_leads(run["id"]) if item["state"] == "shortlisted"]:
        if _halt(store, run["id"]):
            return "cancelled"
        key = normalize_company_key(lead.get("shelf_brand") or "")
        if cap > 0 and key and counts.get(key, 0) >= cap:
            step = {"stage": STAGE_POST_ENRICH, "gate_id": "max_per_company", "passed": False, "reason": f"max {cap} contacts per company reached in this run"}
            store.update_lead(lead["id"], state="post_qa_failed", gates=_merge_gates(lead.get("gates") or [], [step]))
            continue
        apollo_id = (lead.get("person") or {}).get("apollo_id")
        if not apollo_id:
            store.update_lead(lead["id"], state="post_qa_failed")
            continue
        person, charged = meter.enrich(apollo, str(apollo_id))
        search_person = {
            "id": apollo_id,
            "first_name": (lead.get("person") or {}).get("first_name"),
            "last_name": (lead.get("person") or {}).get("last_name"),
            "title": lead.get("title"),
            "city": (lead.get("person") or {}).get("city"),
            "state": (lead.get("person") or {}).get("state"),
            "country": (lead.get("person") or {}).get("country"),
            "organization": (lead.get("person") or {}).get("organization") or {},
        }
        ctx = _ctx(search_person, lead.get("vertical") or "", person)
        env_lead = GateEnv(
            blocklist=blocklist, toggles=values, max_per_company=cap, company_counts=dict(counts),
        )
        steps = evaluate_ids(POST_ENRICH, ctx, env_lead, stage=STAGE_POST_ENRICH)
        gates = _merge_gates(lead.get("gates") or [], steps)
        state = state_from_trail(gates)
        stored = _person_json(search_person, ctx, enriched=True, apollo_id=str(apollo_id))
        stored["organization"] = _org_blob(search_person, person)
        stored["seniority"] = person.get("seniority") or ""
        stored["departments"] = person.get("departments") or []
        stored["linkedin"] = person.get("linkedin_url") or ""
        store.update_lead(
            lead["id"],
            state=state,
            gates=gates,
            person=stored,
            cost_spent=float(lead.get("cost_spent") or 0) + charged,
            **_lead_columns(ctx, lead.get("vertical") or ""),
        )
        if state == "needs_review" and key:
            counts[key] = counts.get(key, 0) + 1
        enriched += 1
    _checkpoint(store, run["id"], 7, "needs_review")
    store.add_event(run["id"], "info", f"Enriched {enriched} contact(s)")
    return f"enriched {enriched}"


def apollo_people_source(store: Any, run: dict[str, Any]) -> str:
    """Run Concert or Venue from the saved stage through the shortlist pause, or through enrich."""
    preset = get_preset(run["preset_id"], store)
    vertical = preset.vertical(run["vertical_id"])
    values = resolve_toggle_values(vertical, run.get("toggles") or {})
    caps = resolve_caps(vertical, {key: int(value) for key, value in (run.get("caps") or {}).items()})
    ensure_snapshot(store, preset)
    blocklist = load_blocklist(store, preset)
    apollo = apollo_factory()
    label = vertical.monday_vertical if vertical.monday_vertical != "from_research" else vertical.label
    stage = int(run.get("stage") or 0)
    params = vertical.source.params

    if stage >= 6:
        return _enrich(store, apollo, run, values, blocklist)

    if stage <= 0:
        _checkpoint(store, run["id"], 0)
        meter = Meter(store, run["id"], "source")
        _search_people(
            store, meter, apollo, run_id=run["id"], vertical_id=vertical.id, label=label, values=values,
            caps=caps, blocklist=blocklist, titles=list(params.get("titles") or []),
            seniorities=list(params.get("seniorities") or []), tiers=_tiers_from_params(params),
        )
        if _halt(store, run["id"]):
            return "cancelled"
        _org_keyword_people(store, apollo, run, vertical, values, caps, blocklist, label)
        if _halt(store, run["id"]):
            return "cancelled"
        stage = 2
        _checkpoint(store, run["id"], 2)

    if vertical.id == "concert_series":
        if stage <= 2:
            _reject_known_bad_orgs(store, run["id"], values)
            _lookup_orgs(store, apollo, run["id"])
            stage = 3
            _checkpoint(store, run["id"], 3)
        if _halt(store, run["id"]):
            return "cancelled"
        if stage <= 3:
            _firmographics(store, run["id"], values, blocklist)
            stage = 4
            _checkpoint(store, run["id"], 4)
        if _halt(store, run["id"]):
            return "cancelled"
        if stage <= 4:
            _spend(store, run, values, caps)
            stage = 5
            _checkpoint(store, run["id"], 5)
    else:
        stage = 5
        _checkpoint(store, run["id"], 5)

    if _halt(store, run["id"]):
        return "cancelled"
    from engine.llm_qa import apply_gemini, gemini_block_reason

    blocked = gemini_block_reason()
    if blocked:
        raise BudgetStop("gemini", blocked)
    ready = _candidates(store, run["id"])
    summary = apply_gemini(store, store.get_run(run["id"]) or run, ready, pass_state="shortlisted")
    shortlisted = store.count_leads(run["id"]).get("shortlisted", 0)
    store.set_status(run["id"], "awaiting_enrich", stage=6, stage_name="Shortlist")
    store.add_event(run["id"], "info", f"Shortlist pause: {shortlisted} contact(s) ready to enrich. {summary}")
    return f"shortlist {shortlisted}"


def free_probe(store: Any, preset: Any, vertical: Any, values: dict[str, Any], caps: Any, *, apollo: Any | None = None) -> dict[str, Any]:
    """
    Stages 0 and 1 only, in memory plus the people-search cache. No credits.
    Returns counts the estimate uses. Does not create a run.
    """
    ensure_snapshot(store, preset)
    blocklist = load_blocklist(store, preset)
    client = apollo or apollo_factory()
    label = vertical.monday_vertical if vertical.monday_vertical != "from_research" else vertical.label
    params = vertical.source.params
    concert = vertical.id == "concert_series"
    revenue = int(values.get("min_revenue") or 0) if concert else None
    ranges = concert_employee_ranges(int(values.get("min_employees") or 0)) if concert else None
    include_similar = not concert
    target = max(0, int(caps.target))
    gate_ids = CONCERT_PRE_ORG if concert else VENUE_PRE_ORG
    env = GateEnv(blocklist=blocklist, toggles=values, max_per_company=int(values.get("max_per_company") or 0))
    meter = Meter(store, "probe", "source")
    seen: set[str] = set()
    companies: list[str] = []
    org_keys: set[str] = set()
    uncached_orgs = 0
    spend_keys: set[str] = set()
    uncached_spend = 0
    survivors = 0

    def _take(person: dict[str, Any]) -> bool:
        nonlocal survivors, uncached_orgs, uncached_spend
        apollo_id = normalize_person_id(person)
        if not apollo_id or apollo_id in seen:
            return survivors >= target
        seen.add(apollo_id)
        ctx = _ctx(person, label)
        steps = evaluate_ids(gate_ids, ctx, env, stage=STAGE_FREE)
        if _pre_state(steps) != "candidate":
            return survivors >= target
        survivors += 1
        companies.append(ctx.org_name)
        key = normalize_company_key(ctx.org_name)
        if concert and key and key not in org_keys:
            org_keys.add(key)
            domain = website_domain_key(ctx.website)
            ident = f"dom:{domain}" if domain else f"name:{key}"
            if cache_fresh(store, "apollo", "org", ident) is None:
                uncached_orgs += 1
        spend_key = company_spend_key(ctx.org_name)
        if concert and values.get("require_spend_evidence") is True and spend_key and spend_key not in spend_keys:
            spend_keys.add(spend_key)
            if cache_fresh(store, "tavily", "spend", spend_key) is None:
                uncached_spend += 1
        return survivors >= target

    for _tier, locations in _locations(vertical.id, values, _tiers_from_params(params)):
        if survivors >= target:
            break
        for title_group in _chunks(list(params.get("titles") or []), int(caps.title_chunk)):
            if survivors >= target:
                break
            for page in range(1, int(caps.max_pages) + 1):
                payload = _people_payload(
                    page=page, titles=title_group, seniorities=list(params.get("seniorities") or []),
                    locations=locations, include_similar=include_similar, revenue_min=revenue, employee_ranges=ranges,
                )
                data = meter.people_search(client, payload)
                stop = False
                for person in _people_of(data):
                    if _take(person):
                        stop = True
                        break
                if stop:
                    break
                total_pages = int((data.get("pagination") or {}).get("total_pages") or page)
                if page >= total_pages or not _people_of(data):
                    break
            if survivors >= target:
                break
    return {
        "survivors": survivors,
        "companies": companies,
        "uncached_orgs": uncached_orgs,
        "uncached_spend_brands": uncached_spend,
    }
