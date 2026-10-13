"""
Research-first brand discovery: Miami events → Tavily search → Cursor extraction → Cursor scoring.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Set, Tuple
from urllib.parse import urlparse

from prospecting_config import MONDAY_VERTICAL_LABELS
from prospecting_qa import company_collides_with_crm, normalize_company_key
from sponsor_llm_extract import extract_sponsors_from_context
from sponsor_tavily_context import gather_event_sponsor_context


def _candidate_quality_score(row: dict) -> int:
    score = 0
    ev = (row.get("sponsorship_evidence") or "").lower()
    name = (row.get("company_name") or "").strip()
    if row.get("evidence_url"):
        score += 3
    if any(x in ev for x in ("official", "presenting", "title partner", "sponsor", "partner")):
        score += 3
    if row.get("discovery_source") == "tavily_cursor":
        score += 2
    if len(ev) >= 40:
        score += 1
    tokens = name.split()
    if len(tokens) == 1 and name and name[0].isupper():
        score += 1
    return score


def _rank_and_cap_candidates(candidates: list[dict], *, per_event_cap: int) -> list[dict]:
    by_event: dict[str, list[dict]] = {}
    for c in candidates:
        ev = (c.get("event_source") or "").strip() or "_"
        by_event.setdefault(ev, []).append(c)

    out: list[dict] = []
    for rows in by_event.values():
        rows.sort(key=_candidate_quality_score, reverse=True)
        out.extend(rows[:per_event_cap])
    out.sort(key=_candidate_quality_score, reverse=True)
    return out


def research_event_sponsors(event: dict) -> List[Dict[str, Any]]:
    """
    Per event: Tavily search (answer + snippets) → Cursor Cloud extracts sponsor brand JSON.
    """
    event_name = (event.get("name") or event.get("event_id") or "event").strip()
    queries = event.get("search_queries") or [f"{event_name} official sponsors partners Miami"]

    try:
        context = gather_event_sponsor_context(event_name, queries)
    except Exception as e:
        print(f"  Tavily search error ({event_name!r}): {e}")
        return []

    n_sources = len(context.get("snippets") or [])
    has_answer = bool((context.get("answer") or "").strip())
    print(f"    Tavily: {n_sources} source(s), answer={'yes' if has_answer else 'no'}")

    try:
        brands = extract_sponsors_from_context(event_name, context)
    except Exception as e:
        print(f"    Cursor extract error ({event_name!r}): {e}")
        return []

    per_event_cap = int(os.getenv("RESEARCH_MAX_BRANDS_PER_EVENT", "12"))
    return _rank_and_cap_candidates(brands, per_event_cap=per_event_cap)


def filter_crm_collisions(
    candidates: Iterable[dict],
    forbidden_company_names: Set[str],
) -> Tuple[List[dict], List[str]]:
    crm_lower = {str(x).strip().lower() for x in forbidden_company_names if str(x).strip()}
    crm_norms = {normalize_company_key(x) for x in crm_lower}
    kept: list[dict] = []
    rejected: list[str] = []
    for c in candidates:
        name = (c.get("company_name") or "").strip()
        if company_collides_with_crm(name, crm_lower, crm_norms):
            rejected.append(name)
            continue
        kept.append(c)
    return kept, rejected


def dedupe_candidates_by_company(candidates: Iterable[dict]) -> List[dict]:
    """
    Keep one row per normalized company name (highest quality score wins).

    Prevents duplicate Apollo passes when the same brand is extracted from
    multiple events/segments in one research run.
    """
    best: dict[str, dict] = {}
    order: list[str] = []
    for c in candidates:
        name = (c.get("company_name") or "").strip()
        key = normalize_company_key(name)
        if not key:
            continue
        if key not in best:
            best[key] = c
            order.append(key)
            continue
        if _candidate_quality_score(c) > _candidate_quality_score(best[key]):
            best[key] = c
    return [best[k] for k in order]


def _domain_from_evidence_url(url: str, company_name: str = "") -> str:
    host = urlparse((url or "").strip()).netloc.lower().removeprefix("www.")
    if not host or "." not in host:
        return ""
    if host.endswith((".gov", ".edu")):
        return ""
    # Event/partner pages often sit on unrelated hosts — skip unless brand appears in domain.
    if company_name:
        brand_key = normalize_company_key(company_name)
        host_stem = host.split(".")[0]
        tokens = [t for t in brand_key.split() if len(t) >= 4]
        if tokens and not any(t in host_stem for t in tokens):
            compact = brand_key.replace(" ", "")
            if len(compact) >= 5 and compact[:5] not in host_stem.replace("-", ""):
                return ""
    return host


def _to_prospect_target(row: dict) -> dict:
    name = (row.get("company_name") or "").strip()
    domain = (row.get("domain") or "").strip()
    if not domain:
        from apollo_brand_domains import guess_brand_domains

        guessed = guess_brand_domains(name)
        if guessed:
            domain = guessed[0]
        else:
            domain = _domain_from_evidence_url(row.get("evidence_url") or "", name)
    cat = (row.get("vertical") or row.get("category") or "").strip()
    if cat not in MONDAY_VERTICAL_LABELS:
        cat = "Lifestyle + Premium Beverage + Entertainment"
    return {
        "company_name": name,
        "name": name,
        "apollo_search_name": (row.get("apollo_search_name") or name).strip(),
        "domain": domain,
        "category": cat,
        "rationale": (row.get("rationale") or row.get("alignment_reason") or "")[:200],
        "sponsorship_evidence": (row.get("sponsorship_evidence") or "")[:500],
        "evidence_url": (row.get("evidence_url") or "").strip(),
        "confidence": int(row.get("confidence") or 0),
        "miami_activity_score": int(row.get("miami_activity_score") or 0),
        "alignment_score": int(row.get("alignment_score") or 0),
        "event_source": (row.get("event_source") or "").strip(),
        "discovery_source": (row.get("discovery_source") or "research"),
        "recommended_angle": (row.get("recommended_angle") or "").strip(),
    }
