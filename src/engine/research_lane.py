"""
Sponsor brand discovery.

Stage 0 spends Tavily and Cursor to turn seed events into shelf brands.
Free gates run before any Apollo org lookup. Cursor scoring runs only on brands that passed
firmographics. The run then pauses. Enrich searches people (free, Florida when that toggle
is on) and buys contacts only for brands the operator did not reject.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from engine.crm import ensure_snapshot, load_blocklist
from engine.gates import GateEnv, evaluate_ids, state_from_trail
from engine.models import resolve_caps, resolve_toggle_values
from engine.presets import get_preset
from engine.spend import Meter, cache_digest, cache_fresh, run_max_tavily_queries
from prospecting_config import MONDAY_VERTICAL_LABELS
from prospecting_qa import normalize_company_key, normalize_email, website_domain_key

ROOT = Path(__file__).resolve().parents[2]
PROMPT_VERSION = "1"

BRAND_FREE = ["brand_plausible", "not_holding_company", "blocklist_company", "protected_account"]
BRAND_FIRMO = [
    "org_name_blocked",
    "non_sponsor_org_name",
    "out_of_market_hospital",
    "org_industry_for_brand",
    "sponsor_org_viable",
]
POST_ENRICH = [
    "email_present",
    "email_blocked",
    "blocklist_email",
    "blocklist_domain",
    "blocklist_name",
    "geo_person_org",
    "title_score_min",
    "prospect_score_min",
    "max_per_company",
]


def _checkpoint(store: Any, run_id: str, stage: int, status: str = "running") -> None:
    from engine.pipeline import STAGE_NAMES

    store.set_status(run_id, status, stage=stage, stage_name=STAGE_NAMES.get(stage, ""))


def _source_id(row: dict[str, Any]) -> str:
    return str(row.get("event_id") or row.get("segment_id") or row.get("name") or "source").strip()


def _source_name(row: dict[str, Any]) -> str:
    return str(row.get("name") or _source_id(row)).strip()


def load_source_rows(vertical: Any, caps: Any) -> list[dict[str, Any]]:
    """The next slice of the event seed. Count comes from the run caps."""
    from underline_knowledge import load_miami_events_seed, rotate_events

    path = str(ROOT / str(vertical.source.params.get("seed_path") or ""))
    rows = load_miami_events_seed(path)
    return rotate_events(rows, max(0, int(caps.events)))


def queries_for(row: dict[str, Any], caps: Any) -> list[str]:
    name = _source_name(row)
    raw = [str(q).strip() for q in (row.get("search_queries") or []) if str(q).strip()]
    if not raw:
        raw = [f"{name} official sponsors partners Miami"]
    return raw[: max(1, int(caps.queries_per_source))]


def gather_context(name: str, queries: list[str]) -> dict[str, Any]:
    from sponsor_tavily_context import gather_event_sponsor_context

    return gather_event_sponsor_context(name, queries)


def search_brief(brief: str) -> dict[str, Any]:
    """One extra Tavily search from the operator's Brief. Bounded to a single query."""
    from tavily import TavilyClient

    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    depth = os.getenv("TAVILY_SEARCH_DEPTH", "basic").strip() or "basic"
    try:
        max_results = int(os.getenv("TAVILY_MAX_RESULTS", "8"))
    except ValueError:
        max_results = 8
    return client.search(
        query=f"{brief.strip()} Miami Florida sponsor partner",
        search_depth=depth,
        max_results=max_results,
        include_answer="basic",
    )


def extract_brands(name: str, context: dict[str, Any]) -> list[dict[str, Any]]:
    from sponsor_llm_extract import extract_sponsors_from_context

    return extract_sponsors_from_context(name, context)


def score_brands(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    from brand_fit_scorer import score_research_candidates
    from underline_knowledge import build_underline_context_block

    context = build_underline_context_block()
    return score_research_candidates(candidates, context=context, max_candidates=max(1, len(candidates)))


def resolve_employers(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from sponsor_employer_resolve import enrich_targets_for_apollo

    return enrich_targets_for_apollo(targets, force_cursor=True)


def make_apollo() -> Any:
    from engine.apollo_lane import apollo_factory

    return apollo_factory()


def run_discover(store: Any, meter: Meter, seed_path: str) -> str:
    """Paid 'Discover new events'. Cached for the TTL, so a resume does not search again."""
    from cursor_model import assert_standard_model
    from miami_events_discover import (
        extract_events_from_research,
        gather_miami_events_research,
        merge_event_seeds,
        save_miami_events_seed,
    )
    from underline_knowledge import load_miami_events_seed

    key = "miami:" + cache_digest({"path": seed_path})
    if cache_fresh(store, "tavily", "discover", key) is not None:
        return "discover cached"
    try:
        wanted = int(os.getenv("MIAMI_EVENTS_TAVILY_QUERIES", "8"))
    except ValueError:
        wanted = 8
    room = run_max_tavily_queries() - meter.tavily_queries_used()
    charge = min(wanted, max(0, int(room)))
    if charge <= 0:
        return "discover skipped, Tavily cap reached"
    meter.charge_source_tavily(charge)
    meter.charge_cursor(1)
    assert_standard_model()
    year = int(os.getenv("MIAMI_EVENTS_YEAR", "2026") or 2026)
    region = os.getenv("MIAMI_EVENTS_REGION", "South Florida").strip() or "South Florida"
    context = gather_miami_events_research(year=year, region=region)
    existing = load_miami_events_seed(seed_path)
    found = extract_events_from_research(
        context,
        year=year,
        region=region,
        existing_names=[str(row.get("name") or "") for row in existing],
    )
    merged, added = merge_event_seeds(existing, found)
    save_miami_events_seed(merged, seed_path)
    store.cache_put("tavily", "discover", key, {"added": added}, charge)
    return f"discover added {added} event(s)"


def _context_key(kind: str, queries: list[str]) -> str:
    depth = os.getenv("TAVILY_SEARCH_DEPTH", "basic").strip() or "basic"
    try:
        max_results = int(os.getenv("TAVILY_MAX_RESULTS", "8"))
    except ValueError:
        max_results = 8
    blob = "|".join(q.strip().lower() for q in queries) + f"|{depth}|{max_results}"
    return f"{kind}:{cache_digest(blob)}"


def _merge_brief(context: dict[str, Any], brief_hit: dict[str, Any]) -> dict[str, Any]:
    merged = dict(context)
    answer = (brief_hit.get("answer") or "").strip()
    if answer:
        merged["answer"] = (str(merged.get("answer") or "") + "\n\n" + answer).strip()
    snippets = list(merged.get("snippets") or [])
    for row in brief_hit.get("results") or []:
        url = (row.get("url") or "").strip()
        if not url:
            continue
        snippets.append(
            {
                "title": (row.get("title") or "")[:200],
                "content": (row.get("content") or "")[:500],
                "url": url,
            }
        )
    merged["snippets"] = snippets[:12]
    return merged


def _verdict(row: dict[str, Any], method: str, min_confidence: int) -> dict[str, str]:
    evidence = "yes" if str(row.get("sponsorship_evidence") or "").strip() else "unclear"
    out = {
        "verdict": "fail",
        "reason": "",
        "region": "Miami",
        "sector": str(row.get("vertical") or row.get("category") or "")[:140],
        "sponsorship_evidence": evidence,
    }
    if method == "heuristic":
        out["reason"] = "heuristic score is not a pass"
        return out
    if row.get("reject"):
        out["reason"] = str(row.get("reject_reason") or "rejected by the scorer")[:140]
        return out
    confidence = int(row.get("confidence") or 0)
    if confidence >= min_confidence and str(row.get("sponsorship_evidence") or "").strip():
        out["verdict"] = "pass"
        out["reason"] = str(row.get("rationale") or row.get("alignment_reason") or f"confidence {confidence}")[:140]
        return out
    out["reason"] = f"confidence {confidence} below {min_confidence}"
    return out


def _brand_ctx(name: str, org: dict[str, Any] | None = None) -> Any:
    from engine.gates import LeadCtx

    org = org or {}
    return LeadCtx(
        vertical_label="",
        shelf_brand=name,
        company=str(org.get("name") or name),
        first="",
        last="",
        title="",
        email="",
        website=website_domain_key(org.get("primary_domain") or org.get("website_url") or ""),
        industry=str(org.get("industry") or ""),
        annual_revenue=org.get("annual_revenue"),
        employees=org.get("estimated_num_employees") or org.get("num_employees"),
        org_city=str(org.get("city") or ""),
        org_state=str(org.get("state") or ""),
        org_country=str(org.get("country") or ""),
    )


def _lookup_org(meter: Meter, apollo: Any, *, domain: str, company: str) -> tuple[dict[str, Any], float]:
    """Domain first, then name. Each miss is 1 credit. Stops once an org id comes back."""
    charged = 0.0
    org: dict[str, Any] = {}
    if domain:
        org, units = meter.org_lookup(apollo, domain=domain, company=company)
        charged += units
    if not org.get("id") and company:
        named, units = meter.org_lookup(apollo, domain="", company=company)
        charged += units
        if named.get("id"):
            org = named
    return org, charged


def _insert_brand(
    store: Any,
    run_id: str,
    *,
    state: str,
    name: str,
    vertical: str,
    gates: list[dict[str, Any]],
    person: dict[str, Any],
    evidence: list[str],
    llm: dict[str, Any] | None,
    cost: float,
) -> dict[str, Any]:
    return store.insert_lead(
        run_id,
        state,
        shelf_brand=name,
        person_name="",
        title="",
        email="",
        domain=website_domain_key((person.get("organization") or {}).get("primary_domain") or ""),
        location="",
        vertical=vertical,
        gates=gates,
        person=person,
        evidence=evidence,
        llm=llm,
        cost_spent=cost,
    )


def _discover_brands(store: Any, run: dict[str, Any], vertical: Any, values: dict[str, Any], caps: Any, blocklist: Any) -> str:
    from cursor_model import assert_standard_model
    from sponsor_research import _rank_and_cap_candidates, _to_prospect_target, dedupe_candidates_by_company

    run_id = run["id"]
    kind = vertical.source.kind
    if not os.getenv("TAVILY_API_KEY", "").strip():
        raise RuntimeError("TAVILY_API_KEY is not set")
    if not os.getenv("CURSOR_API_KEY", "").strip():
        raise RuntimeError("CURSOR_API_KEY is not set")
    if not os.getenv("APOLLO_API_KEY", "").strip():
        raise RuntimeError("APOLLO_API_KEY is not set")
    assert_standard_model()

    store.delete_leads(run_id)
    _checkpoint(store, run_id, 0)
    meter = Meter(store, run_id, "source")
    seed_path = str(ROOT / str(vertical.source.params.get("seed_path") or ""))
    if values.get("discover_new_events"):
        note = run_discover(store, meter, seed_path)
        store.add_event(run_id, "info", note)

    brief = (run.get("brief") or "").strip()
    raw: list[dict[str, Any]] = []
    for source in load_source_rows(vertical, caps):
        name = _source_name(source)
        queries = queries_for(source, caps)
        key_queries = list(queries)
        if brief:
            key_queries.append("brief:" + brief.lower())
        key = _context_key(kind, key_queries)
        cached = cache_fresh(store, "tavily", "context", key)
        if isinstance(cached, dict):
            context = cached
        else:
            units = float(len(queries) + (1 if brief else 0))
            meter.charge_source_tavily(units)
            context = gather_context(name, queries)
            if brief:
                context = _merge_brief(context, search_brief(brief))
            store.cache_put("tavily", "context", key, context, units)
        extract_key = f"{_source_id(source)}:{cache_digest(context)}"
        extracted = cache_fresh(store, "cursor", "extract", extract_key)
        if not isinstance(extracted, list):
            meter.charge_cursor(1)
            assert_standard_model()
            extracted = extract_brands(name, context)
            store.cache_put("cursor", "extract", extract_key, extracted, 1)
        for row in extracted:
            row["event_source"] = name
            raw.append(row)
        store.add_event(run_id, "info", f"{name}: {len(extracted)} brand(s) extracted")

    deduped = dedupe_candidates_by_company(raw)
    env = GateEnv(blocklist=blocklist, toggles=values, max_per_company=int(values.get("max_per_company") or 0))
    survivors: list[dict[str, Any]] = []
    for row in deduped:
        name = str(row.get("company_name") or "").strip()
        steps = evaluate_ids(BRAND_FREE, _brand_ctx(name), env, stage=1)
        if any(not step["passed"] for step in steps):
            _insert_brand(
                store, run_id, state=state_from_trail(steps), name=name,
                vertical=vertical.label, gates=steps, person={"enriched": False, "kind": "brand"},
                evidence=[str(row.get("sponsorship_evidence") or "")], llm=None, cost=0,
            )
            continue
        row["_free_steps"] = steps
        survivors.append(row)

    capped = _rank_and_cap_candidates(survivors, per_event_cap=999)[: max(0, int(caps.brands))]
    targets = []
    for row in capped:
        target = _to_prospect_target(row)
        target["_free_steps"] = list(row.get("_free_steps") or [])
        targets.append(target)
    employer_key = "batch:" + cache_digest([t.get("company_name") for t in targets])
    cached_targets = cache_fresh(store, "cursor", "employer", employer_key)
    if isinstance(cached_targets, list):
        targets = cached_targets
    elif targets:
        meter.charge_cursor(1)
        assert_standard_model()
        targets = resolve_employers(targets)
        store.cache_put("cursor", "employer", employer_key, targets, 1)

    _checkpoint(store, run_id, 2)
    org_meter = Meter(store, run_id, "org")
    apollo = make_apollo()
    ready: list[dict[str, Any]] = []
    for target in targets:
        name = str(target.get("company_name") or "").strip()
        domain = str(target.get("domain") or target.get("apollo_employer_domain") or "").strip()
        org, charged = _lookup_org(org_meter, apollo, domain=domain, company=str(target.get("apollo_search_name") or name))
        ctx = _brand_ctx(name, org)
        steps = list(target.get("_free_steps") or []) + evaluate_ids(BRAND_FIRMO, ctx, env, stage=3)
        if not org.get("id"):
            steps.append({"stage": 2, "gate_id": "org_lookup", "passed": False, "reason": "Apollo did not return an organization"})
        passed = all(step["passed"] for step in steps)
        category = str(target.get("category") or "")
        if category not in MONDAY_VERTICAL_LABELS:
            category = "Lifestyle + Premium Beverage + Entertainment"
        person = {
            "enriched": False,
            "kind": "brand",
            "organization": org,
            "domain": domain,
            "apollo_org_id": str(org.get("id") or ""),
            "shared_employer": bool(target.get("apollo_employer_only")),
            "discovery_source": target.get("discovery_source") or "tavily_cursor",
        }
        evidence = [str(target.get("sponsorship_evidence") or "")]
        if target.get("evidence_url"):
            evidence.append(str(target["evidence_url"]))
        if not passed:
            _insert_brand(
                store, run_id, state=state_from_trail(steps), name=name,
                vertical=category, gates=steps, person=person, evidence=evidence, llm=None, cost=charged,
            )
            continue
        ready.append({"target": target, "org": org, "steps": steps, "person": person, "evidence": evidence, "cost": charged, "category": category})

    _checkpoint(store, run_id, 5)
    score_meter = Meter(store, run_id, "llm")
    scored_rows: list[dict[str, Any]] = []
    method = "cursor_cloud"
    if ready:
        pending = [item["target"] for item in ready]
        uncached = []
        for target in pending:
            key = f"{vertical.id}:{normalize_company_key(target.get('company_name') or '')}:{PROMPT_VERSION}"
            hit = cache_fresh(store, "cursor", "score", key)
            if isinstance(hit, dict):
                scored_rows.append(hit)
            else:
                uncached.append(target)
        if uncached:
            batch = max(1, int(os.getenv("CURSOR_SCORE_BATCH_SIZE", "6") or 6))
            score_meter.charge_cursor(float((len(uncached) + batch - 1) // batch))
            assert_standard_model()
            try:
                fresh, method = score_brands(uncached)
            except Exception:
                fresh, method = [], "error"
            by_name = {str(row.get("company_name") or "").strip().lower(): row for row in fresh}
            for target in uncached:
                row = by_name.get(str(target.get("company_name") or "").strip().lower()) or dict(target)
                if method == "error":
                    row = {**target, "confidence": 0}
                key = f"{vertical.id}:{normalize_company_key(target.get('company_name') or '')}:{PROMPT_VERSION}"
                store.cache_put("cursor", "score", key, {**row, "_method": method}, 1)
                scored_rows.append({**row, "_method": method})
        else:
            method = str((scored_rows[0] or {}).get("_method") or "cursor_cloud")

    by_score = {str(row.get("company_name") or "").strip().lower(): row for row in scored_rows}
    min_confidence = int(values.get("min_confidence") or 80)
    shortlisted = 0
    for item in ready:
        target = item["target"]
        scored = by_score.get(str(target.get("company_name") or "").strip().lower()) or {}
        used_method = str(scored.get("_method") or method)
        if used_method == "error":
            llm = {
                "verdict": "fail",
                "reason": "LLM unavailable",
                "region": "Miami",
                "sector": item["category"][:140],
                "sponsorship_evidence": "unclear",
            }
        else:
            llm = _verdict({**target, **scored}, used_method, min_confidence)
        state = "llm_failed" if llm["verdict"] == "fail" or llm["reason"] == "LLM unavailable" else "shortlisted"
        _insert_brand(
            store, run_id, state=state, name=str(target.get("company_name") or ""),
            vertical=item["category"], gates=item["steps"], person=item["person"],
            evidence=item["evidence"], llm=llm, cost=item["cost"],
        )
        if state == "shortlisted":
            shortlisted += 1

    store.set_status(run_id, "awaiting_enrich", stage=6, stage_name="Shortlist")
    store.add_event(run_id, "info", f"Shortlist pause: {shortlisted} brand(s) ready. Reject any you do not want, then enrich.")
    return f"shortlist {shortlisted}"


def _search_lists(params: dict[str, Any]) -> tuple[list[str], list[str]]:
    titles = [str(item).strip() for item in (params.get("titles") or []) if str(item).strip()]
    seniorities = [str(item).strip() for item in (params.get("seniorities") or []) if str(item).strip()]
    if not titles:
        raise RuntimeError("This vertical has no search titles. Set them on the Preset screen.")
    return titles, seniorities


def _person_locations(values: dict[str, Any], params: dict[str, Any]) -> list[str] | None:
    if values.get("florida_person_only", True):
        return [str(item).strip() for item in (params.get("florida_person_locations") or []) if str(item).strip()]
    if values.get("require_us", True):
        return [str(item).strip() for item in (params.get("us_person_locations") or []) if str(item).strip()]
    return None


def _people_of(data: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("people", "contacts"):
        rows = data.get(key)
        if isinstance(rows, list):
            return rows
    return []


def _contact_ctx(lead: dict[str, Any], person: dict[str, Any], enriched: dict[str, Any]) -> Any:
    from engine.apollo_lane import _ctx

    search = {
        "first_name": person.get("first_name") or "",
        "last_name": person.get("last_name") or person.get("last_name_obfuscated") or "",
        "title": person.get("title") or "",
        "city": person.get("city") or "",
        "state": person.get("state") or "",
        "country": person.get("country") or "",
        "organization": (lead.get("person") or {}).get("organization") or person.get("organization") or {},
    }
    return _ctx(search, lead.get("vertical") or "", enriched)


def _store_contact(
    store: Any,
    run_id: str,
    lead: dict[str, Any],
    *,
    state: str,
    gates: list[dict[str, Any]],
    ctx: Any,
    enriched_person: dict[str, Any],
    apollo_id: str,
    cost: float,
    reuse_id: str | None,
) -> None:
    from engine.apollo_lane import _lead_columns, _org_blob, _person_json

    search = {
        "first_name": ctx.first,
        "title": ctx.title,
        "organization": (lead.get("person") or {}).get("organization") or {},
    }
    stored = _person_json(search, ctx, enriched=True, apollo_id=apollo_id)
    stored["organization"] = _org_blob(search, enriched_person)
    stored["seniority"] = enriched_person.get("seniority") or ""
    stored["departments"] = enriched_person.get("departments") or []
    stored["linkedin"] = enriched_person.get("linkedin_url") or ""
    stored["kind"] = "contact"
    columns = _lead_columns(ctx, lead.get("vertical") or "")
    fields = dict(
        state=state,
        gates=gates,
        person=stored,
        llm=lead.get("llm"),
        evidence=lead.get("evidence") or [],
        cost_spent=cost,
        **columns,
    )
    if reuse_id:
        store.update_lead(reuse_id, **fields)
    else:
        store.insert_lead(run_id, **fields)


def _enrich_brands(store: Any, run: dict[str, Any], vertical: Any, values: dict[str, Any], blocklist: Any) -> str:
    from apollo_contact_rank import prefer_us_candidates, rank_contacts_for_sponsorship, should_enrich_person

    run_id = run["id"]
    _checkpoint(store, run_id, 6, "enriching")
    meter = Meter(store, run_id, "enrich")
    apollo = make_apollo()
    cap = int(values.get("max_per_company") or 0)
    params = vertical.source.params
    titles, seniorities = _search_lists(params)
    locations = _person_locations(values, params)
    enriched = 0
    counts: dict[str, int] = {}
    for lead in [item for item in store.list_leads(run_id) if item["state"] == "shortlisted"]:
        person_blob = lead.get("person") or {}
        org_id = str(person_blob.get("apollo_org_id") or "")
        org = person_blob.get("organization") or {}
        shelf = lead.get("shelf_brand") or ""
        shared = bool(person_blob.get("shared_employer")) or (
            bool(org.get("name")) and normalize_company_key(org.get("name")) != normalize_company_key(shelf)
        )
        if not org_id:
            store.update_lead(
                lead["id"],
                state="qa_failed",
                gates=(lead.get("gates") or []) + [
                    {"stage": 2, "gate_id": "org_lookup", "passed": False, "reason": "no Apollo organization id"}
                ],
            )
            continue
        payload = {
            "page": 1,
            "per_page": 25,
            "organization_ids": [org_id],
            "person_titles": titles,
            "person_seniorities": seniorities,
            "include_similar_titles": True,
            "contact_email_status": ["verified"],
        }
        if locations:
            payload["person_locations"] = locations
        data = meter.people_search(apollo, payload)
        people = prefer_us_candidates(_people_of(data), require_us=bool(values.get("require_us", True)))
        people = rank_contacts_for_sponsorship(people, shelf_brand=shelf, shared_employer=shared)
        passers: list[dict[str, Any]] = []
        fail_reason = "no contact passed the title gates"
        for person in people[:8]:
            ok, reason, _score = should_enrich_person(
                person, shelf_brand=shelf, shared_employer=shared, research_mode=True, min_title_score=45,
            )
            if ok:
                passers.append(person)
            else:
                fail_reason = reason
            if cap > 0 and len(passers) >= cap:
                break
        if not passers:
            store.update_lead(
                lead["id"],
                state="qa_failed",
                gates=(lead.get("gates") or []) + [
                    {"stage": 1, "gate_id": "should_enrich", "passed": False, "reason": fail_reason}
                ],
            )
            continue
        reuse = lead["id"]
        company_key = normalize_company_key(shelf)
        for person in passers:
            if cap > 0 and company_key and counts.get(company_key, 0) >= cap:
                break
            apollo_id = str(person.get("id") or "")
            bought, charged = meter.enrich(apollo, apollo_id)
            bought = bought or {}
            ctx = _contact_ctx(lead, person, bought)
            env = GateEnv(
                blocklist=blocklist, toggles=values, max_per_company=cap, company_counts=dict(counts),
            )
            pre = [{"stage": 1, "gate_id": "should_enrich", "passed": True, "reason": ""}]
            steps = list(lead.get("gates") or []) + pre + evaluate_ids(POST_ENRICH, ctx, env, stage=7)
            state = state_from_trail(steps)
            email = normalize_email(bought.get("email") or "")
            if email:
                env.seen_emails.add(email)
            cost = float(lead.get("cost_spent") or 0) + charged if reuse == lead["id"] else charged
            _store_contact(
                store, run_id, lead, state=state, gates=steps, ctx=ctx, enriched_person=bought,
                apollo_id=apollo_id, cost=cost, reuse_id=reuse,
            )
            reuse = None
            if state == "needs_review" and company_key:
                counts[company_key] = counts.get(company_key, 0) + 1
            enriched += 1
    _checkpoint(store, run_id, 7, "needs_review")
    store.add_event(run_id, "info", f"Enriched {enriched} contact(s)")
    return f"enriched {enriched}"


def research_source(store: Any, run: dict[str, Any]) -> str:
    """Sponsor brands, from the event seed through the shortlist pause or through enrich."""
    preset = get_preset(run["preset_id"], store)
    vertical = preset.vertical(run["vertical_id"])
    values = resolve_toggle_values(vertical, run.get("toggles") or {})
    caps = resolve_caps(vertical, {key: int(value) for key, value in (run.get("caps") or {}).items()})
    ensure_snapshot(store, preset)
    blocklist = load_blocklist(store, preset)
    if int(run.get("stage") or 0) >= 6:
        return _enrich_brands(store, run, vertical, values, blocklist)
    return _discover_brands(store, run, vertical, values, caps, blocklist)
