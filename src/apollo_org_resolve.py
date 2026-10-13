"""
Resolve shelf-brand targets to the correct Apollo employer, then fetch US marketing contacts.

Apollo name search alone often returns wrong homonyms (DESIGN OREO, Organizacion Corona).
We prefer domain search + US HQ + industry sanity checks, and known employer overrides
(e.g. Budweiser marketers sit under Anheuser-Busch USA in Apollo).
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from apollo_brand_domains import guess_brand_domains
from apollo_client import ApolloClient
from brand_targeting import (
    brand_apollo_employer_hint,
    is_beverage_distributor_or_wholesaler,
)
from apollo_contact_rank import rank_contacts_for_sponsorship
from prospecting_config import (
    APOLLO_FL_PERSON_LOCATIONS,
    APOLLO_US_PERSON_LOCATIONS,
    DEFAULT_PERSON_SENIORITIES,
    DEFAULT_PERSON_TITLES,
    SPONSORSHIP_APOLLO_SEARCH_TITLES,
)
from prospecting_qa import normalize_company_key, org_industry_blocked

US_ORG_LOCATIONS = ["United States"]

_LEGAL_SUFFIX_RE = re.compile(
    r"\s*,?\s*\b(inc\.?|incorporated|corporation|corp\.?|llc|l\.l\.c\.?|ltd\.?|plc|co\.?|company|s\.?a\.?|gmbh)\s*$",
    re.I,
)

_WRONG_ORG_NAME_MARKERS = (
    "design ",
    "consult",
    "organizacion",
    "organización",
    "grupo modelo",
    "hospital",
    "clinic",
    "remedies",
    "foundation",
    "sanatorio",
    "photography",
    "photo studio",
)

_EMPLOYER_HOMONYM_JUNK = (
    "photography",
    "photo",
    "studio",
    "consulting",
    "real estate",
    "church",
    "restaurant",
)

_BAD_DOMAIN_ORG_INDUSTRIES = (
    "information technology",
    "mechanical or industrial",
    "management consulting",
    "staffing",
    "facilities services",
)

_ORG_TOKEN_STOP = frozenset(
    {"usa", "us", "inc", "llc", "co", "company", "group", "the", "and", "of"}
)

_ORG_DESC_EXTRA = frozenset(
    {
        "distillery",
        "brewery",
        "winery",
        "beverages",
        "brands",
        "holdings",
        "international",
        "corporation",
        "enterprises",
    }
)


def _significant_brand_tokens(brand: str) -> set[str]:
    tokens = normalize_company_key(brand).split()
    out: set[str] = set()
    for t in tokens:
        if not t or t in _ORG_TOKEN_STOP:
            continue
        if t == "usa" or len(t) >= 4:
            out.add(t)
        elif len(tokens) <= 2:
            out.add(t)
    return out


def _brand_org_token_fit(brand: str, org_name: str) -> float:
    """1.0 = all distinctive brand tokens appear in org name; lower = likely homonym."""
    brand_tokens = _significant_brand_tokens(brand)
    if not brand_tokens:
        return 1.0
    org_tokens = set(normalize_company_key(org_name).split())
    missing = brand_tokens - org_tokens
    overlap = (len(brand_tokens) - len(missing)) / len(brand_tokens)
    extra = {
        t
        for t in org_tokens - brand_tokens
        if t not in _ORG_TOKEN_STOP and t not in _ORG_DESC_EXTRA and len(t) >= 4
    }
    if extra:
        overlap -= 0.4 * len(extra)
    return max(0.0, overlap)


def _unique_strs(items: List[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for raw in items:
        s = (raw or "").strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _employer_aliases_from_hint(hint: Dict[str, str]) -> List[str]:
    raw = hint.get("apollo_search_aliases")
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    except (json.JSONDecodeError, TypeError):
        pass
    return [a.strip() for a in str(raw).split(",") if a.strip()]


def employer_search_names(hint: Dict[str, str]) -> List[str]:
    """Apollo org name variants for a Cursor-inferred employer hint."""
    names: List[str] = []
    primary = (hint.get("apollo_search_name") or "").strip()
    if primary:
        names.append(primary)
    names.extend(_employer_aliases_from_hint(hint))
    out: List[str] = []
    for n in names:
        out.extend(organization_name_variants(n))
    return _unique_strs(out)


def employer_search_domains(
    hint: Dict[str, str],
    *,
    shelf_brand: str = "",
    shelf_domain: Optional[str] = None,
    employer_only: bool = False,
) -> List[str]:
    domains: List[str] = []
    if hint.get("domain"):
        domains.append(_domain_key(hint["domain"]))
    emp = (hint.get("apollo_search_name") or "").strip()
    domains.extend(guess_brand_domains(emp))
    if not employer_only:
        if shelf_domain:
            domains.append(_domain_key(shelf_domain))
        if shelf_brand:
            domains.extend(guess_brand_domains(shelf_brand))
    return _unique_strs([d for d in domains if d and "." in d])


def _employer_org_matches_hint(hint: Dict[str, str], org_name: str) -> bool:
    names = [(hint.get("apollo_search_name") or "").strip(), *_employer_aliases_from_hint(hint)]
    return any(n and organization_names_match(n, org_name) for n in names)


def person_org_acceptable(
    shelf_brand: str,
    org_name: str,
    employer_hint: Optional[Dict[str, str]] = None,
) -> bool:
    """
    Reject homonym orgs on people-search fallback (e.g. MINI USA vs Mini Melts USA).
    When an employer hint exists, the org must match the employer — not a shelf-brand homonym.
    """
    if employer_hint:
        return _employer_org_matches_hint(employer_hint, org_name)
    fit = _brand_org_token_fit(shelf_brand, org_name)
    if fit < 0.65:
        return False
    return organization_names_match(shelf_brand, org_name) or fit >= 0.85


def organization_name_variants(company_name: str) -> List[str]:
    base = (company_name or "").strip()
    if not base:
        return []

    out: List[str] = []
    seen: set[str] = set()

    def add(s: str) -> None:
        s = re.sub(r"\s+", " ", (s or "").strip())
        if not s:
            return
        key = s.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(s)

    add(base)
    stripped = _LEGAL_SUFFIX_RE.sub("", base).strip()
    add(stripped)
    if base.lower().startswith("the "):
        add(base[4:].strip())
    words = stripped.split()
    if len(words) >= 2:
        add(" ".join(words[:2]))
    return out


def organization_names_match(target: str, candidate: str) -> bool:
    t = normalize_company_key(target)
    c = normalize_company_key(candidate)
    if not t or not c:
        return False
    if t == c:
        return True
    if len(t) >= 6 and len(c) >= 6 and (t in c or c in t):
        return True
    t_tokens = {w for w in t.split() if len(w) >= 3}
    c_tokens = {w for w in c.split() if len(w) >= 3}
    if not t_tokens or not c_tokens:
        return False
    shorter, longer = (t_tokens, c_tokens) if len(t_tokens) <= len(c_tokens) else (c_tokens, t_tokens)
    if len(shorter) >= 2 and shorter.issubset(longer):
        return True
    return False


def _domain_key(domain: str) -> str:
    d = (domain or "").strip().lower()
    d = re.sub(r"^https?://", "", d)
    return d.split("/")[0].removeprefix("www.")


def _org_country_us(org: Dict[str, Any]) -> bool:
    c = (org.get("country") or "").strip().lower()
    if not c:
        return True
    return c in ("united states", "us", "usa") or "united states" in c


def _org_name_suspicious(target: str, org_name: str) -> bool:
    n = (org_name or "").lower()
    t = (target or "").lower()
    for m in _WRONG_ORG_NAME_MARKERS:
        if m in n and m not in t:
            return True
    if "oreo" in t and "design" in n:
        return True
    if "corona" in t and "organizacion" in n:
        return True
    if "modelo" in t and "grupo modelo" in n:
        return True
    if "mountain dew" in t and "mountain dev" in n:
        return True
    if t == "patron" and "technology" in n:
        return True
    if "grey goose" in t and "graphic" in n:
        return True
    if "perrier" in t and "graphics" in n:
        return True
    if t == "lacoste" and ("perrier" in n or "gallery" in n or "lucy" in n):
        return True
    return False


def _brand_homonym_org(brand: str, org_name: str) -> bool:
    """Reject Apollo orgs that share a name with the brand but are unrelated companies."""
    b = normalize_company_key(brand)
    n = normalize_company_key(org_name)
    if not b or not n:
        return False
    pairs = (
        ("patron", "technology"),
        ("grey goose", "graphic"),
        ("oreo", "design"),
        ("corona", "organizacion"),
        ("modelo", "grupo modelo"),
    )
    for brand_key, bad in pairs:
        if brand_key in b and bad in n:
            return True
    return False


def _score_org_candidate(
    target: str,
    org: Dict[str, Any],
    *,
    domain: Optional[str] = None,
    match_name: Optional[str] = None,
    shelf_brand: Optional[str] = None,
) -> float:
    name = (org.get("name") or "").strip()
    if not name:
        return -999.0

    score = 0.0
    want_domain = _domain_key(domain) if domain else ""
    org_domain = _domain_key(
        org.get("primary_domain") or org.get("website_url") or org.get("domain") or ""
    )

    domain_verified = bool(want_domain and org_domain and org_domain == want_domain)
    if domain_verified:
        score += 150.0
    elif want_domain and org_domain and want_domain in org_domain:
        score += 90.0

    label = match_name or target
    token_fit = _brand_org_token_fit(shelf_brand or target, name)
    score += token_fit * 80.0

    if organization_names_match(label, name):
        score += 40.0
    else:
        t = normalize_company_key(label)
        c = normalize_company_key(name)
        if t and c and len(t) >= 5 and (t in c or c in t):
            score += 20.0

    if shelf_brand and _brand_homonym_org(shelf_brand, name):
        score -= 200.0

    industry = (org.get("industry") or "").lower()
    if is_beverage_distributor_or_wholesaler(name, industry):
        score -= 200.0

    if not _org_country_us(org):
        score -= 90.0

    trust_industry = domain_verified and token_fit >= 0.85
    if "information technology" in industry:
        score -= 100.0
        if domain_verified:
            score -= 80.0
    if not trust_industry:
        if org_industry_blocked(industry):
            score -= 120.0
        for bad in _BAD_DOMAIN_ORG_INDUSTRIES:
            if bad in industry:
                score -= 80.0

    if _org_name_suspicious(target, name):
        score -= 150.0

    if not domain_verified and token_fit < 0.65:
        score -= 100.0

    try:
        emp = int(org.get("estimated_num_employees") or org.get("num_employees") or 0)
        if emp >= 500:
            score += 8.0
    except (TypeError, ValueError):
        pass

    return score


def _dedupe_org_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for org in candidates:
        oid = str(org.get("id") or org.get("organization_id") or "")
        if oid and oid in seen:
            continue
        if oid:
            seen.add(oid)
        out.append(org)
    return out


def _collect_org_candidates(
    apollo: ApolloClient,
    *,
    search_names: List[str],
    domains: Optional[List[str]] = None,
    domain_only: bool = False,
) -> List[Dict[str, Any]]:
    seen_ids: set[str] = set()
    candidates: List[Dict[str, Any]] = []

    def add_orgs(data: Optional[Dict[str, Any]]) -> None:
        for org in apollo.orgs_from_search_response(data):
            oid = str(org.get("id") or org.get("organization_id") or "")
            if oid and oid not in seen_ids:
                seen_ids.add(oid)
                candidates.append(org)

    for domain in domains or []:
        if not domain:
            continue
        add_orgs(
            apollo.search_organization_by_domain(
                domain, per_page=10, organization_locations=US_ORG_LOCATIONS
            )
        )
        add_orgs(apollo.search_organization_by_domain(domain, per_page=10))

    if domain_only:
        return candidates

    for variant in search_names:
        add_orgs(
            apollo.search_organization_by_name(
                variant, per_page=15, organization_locations=US_ORG_LOCATIONS
            )
        )

    return candidates


def resolve_apollo_organization(
    apollo: ApolloClient,
    company_name: str,
    *,
    domain: Optional[str] = None,
    apollo_search_name: Optional[str] = None,
    employer_hint: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    """Best Apollo org for this shelf brand (US employer preferred)."""
    hint = employer_hint or brand_apollo_employer_hint(company_name)
    employer_only = bool(
        hint and str(hint.get("employer_only", "")).lower() in ("1", "true", "yes")
    )
    domain_only_search = False
    if hint:
        search_names = employer_search_names(hint)
        domains = employer_search_domains(
            hint,
            shelf_brand=company_name,
            shelf_domain=domain,
            employer_only=employer_only,
        )
        match_name = hint["apollo_search_name"] if employer_only else company_name
        domain_only_search = False
    else:
        search_names = organization_name_variants(apollo_search_name or company_name)
        if apollo_search_name and apollo_search_name not in search_names:
            search_names.insert(0, apollo_search_name)
        guessed = guess_brand_domains(company_name)
        domains = []
        for d in [domain, *guessed]:
            if d and d not in domains:
                domains.append(d)
        match_name = company_name

    primary_domain = domains[0] if domains else (domain or None)

    if hint:
        candidates = _dedupe_org_candidates(
            _collect_org_candidates(
                apollo,
                search_names=search_names,
                domains=domains,
                domain_only=False,
            )
        )
    else:
        candidates = _collect_org_candidates(
            apollo,
            search_names=[] if domains else search_names,
            domains=domains,
            domain_only=bool(domains),
        )
        if domains:
            candidates = _dedupe_org_candidates(
                candidates
                + _collect_org_candidates(
                    apollo,
                    search_names=search_names,
                    domains=[],
                    domain_only=False,
                )
            )
    if not candidates:
        return None

    best: Optional[Dict[str, Any]] = None
    best_score = -999.0
    for org in candidates:
        score = _score_org_candidate(
            company_name,
            org,
            domain=primary_domain,
            match_name=match_name,
            shelf_brand=company_name,
        )
        if score > best_score:
            best_score = score
            best = org

    if not best or best_score < 70.0:
        return None

    if employer_only and hint:
        best_name = (best.get("name") or "").strip()
        if _employer_org_is_homonym(hint, best_name):
            return None
        org_dom = _domain_key(
            best.get("primary_domain") or best.get("website_url") or best.get("domain") or ""
        )
        trusted_domains = set(
            employer_search_domains(
                hint,
                shelf_brand=company_name,
                shelf_domain=domain,
                employer_only=True,
            )
        )
        domain_ok = bool(org_dom and org_dom in trusted_domains)
        if not _employer_org_matches_hint(hint, best_name) and not domain_ok:
            return None
        if not domain_ok and _brand_org_token_fit(company_name, best_name) < 0.65:
            return None

    oid = best.get("id") or best.get("organization_id")
    if not oid:
        return None

    best_name = (best.get("name") or company_name).strip()
    brand_aligned = organization_names_match(company_name, best_name)
    # Shared employer ONLY when we intentionally resolved a parent (employer_only).
    # Do NOT treat fuzzy Apollo renames (YouFit Gyms vs Youfit Health Clubs) as shared —
    # that wrongly requires brand-in-title and kills normal marketing contacts.
    shared_employer = bool(hint and employer_only) and not brand_aligned
    return {
        "id": str(oid),
        "name": best_name,
        "score": best_score,
        "shared_employer": shared_employer,
        "raw": best,
    }


def _people_from_response(data: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not data:
        return []
    return list(data.get("people") or data.get("contacts") or [])


def _employer_org_is_homonym(hint: Dict[str, str], org_name: str) -> bool:
    n = (org_name or "").lower()
    if any(j in n for j in _EMPLOYER_HOMONYM_JUNK):
        return True
    emp = (hint.get("apollo_search_name") or "").lower()
    if "heineken" in emp and "heineken" in n and "usa" not in n and "photography" in n:
        return True
    return False


def _resolve_person_locations(
    *,
    relax_locations: bool,
    person_locations: Optional[List[str]],
    require_florida: bool,
    shared_employer: bool = False,
) -> List[str]:
    if person_locations:
        return person_locations
    if relax_locations:
        return APOLLO_US_PERSON_LOCATIONS
    # Shared employers: national Apollo search; Florida enforced in post-enrich QA.
    if require_florida and shared_employer:
        return APOLLO_US_PERSON_LOCATIONS
    if require_florida:
        return APOLLO_FL_PERSON_LOCATIONS
    return APOLLO_US_PERSON_LOCATIONS


def _dedupe_people(people: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for p in people:
        pid = str(p.get("id") or p.get("apollo_id") or "")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        out.append(p)
    return out


def _merge_people_fl_first(
    primary: List[Dict[str, Any]],
    secondary: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """FL (or other primary) hits first, then US-wide pool without duplicates."""
    return _dedupe_people(list(primary) + list(secondary))


def _search_people_at_org(
    apollo: ApolloClient,
    org_id: str,
    *,
    titles: List[str],
    person_locations: Optional[List[str]] = None,
    max_pages: int = 3,
    require_verified_email: bool = True,
) -> List[Dict[str, Any]]:
    locs = person_locations or APOLLO_US_PERSON_LOCATIONS
    people: List[Dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        data = apollo.search_people_by_orgs(
            organization_ids=[org_id],
            person_titles=titles,
            person_seniorities=DEFAULT_PERSON_SENIORITIES,
            page=page,
            per_page=25,
            person_locations=locs,
            require_verified_email=require_verified_email,
        )
        batch = _people_from_response(data)
        if not batch:
            break
        people.extend(batch)
    return people


def _search_people_with_fallbacks(
    apollo: ApolloClient,
    org_id: str,
    *,
    max_pages: int,
    person_locations: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Apollo returns zero rows when filters stack too aggressively (e.g. q_keywords + org + titles).
    Try sponsorship titles first, then broaden location and title net.
    """
    locs = person_locations or APOLLO_US_PERSON_LOCATIONS
    attempts: list[tuple[List[str], Optional[List[str]], bool]] = [
        (SPONSORSHIP_APOLLO_SEARCH_TITLES, locs, True),
        (SPONSORSHIP_APOLLO_SEARCH_TITLES, None, True),
        (DEFAULT_PERSON_TITLES, None, True),
        (DEFAULT_PERSON_TITLES, None, False),
    ]
    for titles, loc, verified in attempts:
        batch = _search_people_at_org(
            apollo,
            org_id,
            titles=titles,
            person_locations=loc,
            max_pages=max_pages,
            require_verified_email=verified,
        )
        if batch:
            return batch
    return []


def _tiered_people_at_org(
    apollo: ApolloClient,
    org_id: str,
    *,
    titles: List[str],
    max_pages: int,
    us_wide: bool,
    require_florida: bool,
    shared_employer: bool,
) -> List[Dict[str, Any]]:
    """
    Search by org + titles without person_locations.

    Apollo api_search often omits city/state until enrich; person_locations then
  drops real contacts (e.g. Four Loko). FL/South preference is applied in ranking/QA.
    """
    del us_wide, require_florida, shared_employer
    people = _search_people_at_org(
        apollo,
        org_id,
        titles=titles,
        person_locations=None,
        max_pages=max_pages,
    )
    if people:
        return people
    return _search_people_with_fallbacks(apollo, org_id, max_pages=max_pages)


def fetch_people_for_target_company(
    apollo: ApolloClient,
    company_name: str,
    *,
    apollo_search_name: Optional[str] = None,
    domain: Optional[str] = None,
    employer_hint: Optional[Dict[str, str]] = None,
    relax_locations: bool = False,
    person_locations: Optional[List[str]] = None,
    organization_locations: Optional[List[str]] = None,
    max_pages: int = 3,
    require_florida: bool = False,
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Resolve org → people. Shared employers search US-wide in Apollo when FL required;
    person-in-Florida is enforced in post-enrich QA.
    """
    del organization_locations

    resolved = resolve_apollo_organization(
        apollo,
        company_name,
        domain=domain,
        apollo_search_name=apollo_search_name,
        employer_hint=employer_hint,
    )

    shared_employer = bool(resolved and resolved.get("shared_employer"))
    if (
        not shared_employer
        and employer_hint
        and str(employer_hint.get("employer_only", "")).lower() in ("1", "true", "yes")
        and resolved
        and not organization_names_match(company_name, resolved.get("name") or "")
    ):
        shared_employer = True
    us_wide = relax_locations or not require_florida
    locs = _resolve_person_locations(
        relax_locations=relax_locations,
        person_locations=person_locations,
        require_florida=require_florida,
        shared_employer=shared_employer,
    )

    people: List[Dict[str, Any]] = []

    def _people_for_resolved(org: Dict[str, Any]) -> List[Dict[str, Any]]:
        def _people_for_titles(titles: List[str]) -> List[Dict[str, Any]]:
            return _tiered_people_at_org(
                apollo,
                org["id"],
                titles=titles,
                max_pages=max_pages,
                us_wide=us_wide,
                require_florida=require_florida and not relax_locations,
                shared_employer=shared_employer,
            )

        batch = _people_for_titles(SPONSORSHIP_APOLLO_SEARCH_TITLES)
        # Thin sponsorship-title pools are common for mid-size brands — widen net.
        if len(batch) < 8:
            wider = _people_for_titles(DEFAULT_PERSON_TITLES)
            if wider:
                batch = _dedupe_people(list(batch) + list(wider))
        return batch

    if resolved:
        people = _people_for_resolved(resolved)

    if employer_hint and not people:
        parent_hint = dict(employer_hint)
        parent_hint["employer_only"] = "true"
        parent_domain = _domain_key(parent_hint.get("domain") or "") or domain
        parent_resolved = resolve_apollo_organization(
            apollo,
            company_name,
            domain=parent_domain,
            apollo_search_name=apollo_search_name,
            employer_hint=parent_hint,
        )
        if parent_resolved and (not resolved or parent_resolved["id"] != resolved.get("id")):
            resolved = parent_resolved
            shared_employer = not organization_names_match(
                company_name, parent_resolved.get("name") or ""
            )
            people = _people_for_resolved(resolved)

    if not people:
        if employer_hint:
            fallback_names = employer_search_names(employer_hint)
        else:
            fallback_names = organization_name_variants(apollo_search_name or company_name)
        for variant in fallback_names:
            payload: Dict[str, Any] = {
                "page": 1,
                "per_page": 25,
                "person_titles": SPONSORSHIP_APOLLO_SEARCH_TITLES,
                "q_organization_name": variant,
                "include_similar_titles": True,
                "contact_email_status": ["verified"],
            }
            data = apollo.search_people(payload)
            for p in _people_from_response(data):
                org = p.get("organization") or {}
                remote = (org.get("name") or "").strip()
                if remote and person_org_acceptable(company_name, remote, employer_hint):
                    people.append(p)
            if people:
                break

    people = rank_contacts_for_sponsorship(
        _dedupe_people(people),
        shelf_brand=company_name,
        shared_employer=shared_employer,
    )
    return resolved, people
