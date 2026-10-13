"""
QA for Concert Series (Miami Music Series) prospecting.

Email-only Monday dedupe, plus company/domain skip for accounts already in
Replied / Meeting / Closed Won. Firmographic gates reuse sponsor_org_viable
(brand mode), org_industry_blocked, and org_name_blocked. Paid-title gate
rejects community / collab desks unless the title also has paid-buyer context.
"""
from __future__ import annotations

from typing import Any, Optional, Set, Tuple

from concert_series_config import concert_min_org_employees, concert_min_org_revenue
from prospecting_qa import (
    company_collides_with_crm,
    email_blocked,
    email_domain_key,
    is_personal_email_domain,
    normalize_company_key,
    normalize_email,
    org_industry_blocked,
    org_name_blocked,
    parse_annual_revenue_usd,
    sponsor_org_viable,
    website_domain_key,
)

CONCERT_TITLE_ALLOW_SUBSTRINGS = [
    "sponsor",
    "sponsorship",
    "partner",
    "partnership",
    "brand",
    "marketing",
    "experiential",
    "entertainment",
    "festival",
    "hospitality",
    "activation",
    "community",
    "communications",
    "cmo",
    "chief marketing",
    "events",
    "trade marketing",
]

CONCERT_TITLE_BLOCK_SUBSTRINGS = [
    "intern",
    "assistant to",
    " administrative assistant",
    "receptionist",
    "office manager",
    "help desk",
    "it support",
    "recruiter",
    "talent acquisition",
    "paralegal",
    "attorney",
    "counsel",
    "professor",
    "lecturer",
    "wedding",
    "software engineer",
    "data scientist",
    "devops",
    "privacy",
    "data security",
    "information security",
    "internal audit",
    "director of finance",
    "director, finance",
    " fp&a",
    "fp&a ",
    "financial planning",
    "controller",
    "accounting",
    "procurement",
    "store manager",
    "assistant store",
    "shift manager",
    "staffing",
]

# Collab / community desks fail unless a paid-buyer token is also present.
_COLLAB_ALONE_SUBSTRINGS = (
    "community",
    "communications",
    "partner",
    "events",
    "hospitality",
)
_PAID_TITLE_CONTEXT = (
    "sponsor",
    "experiential",
    "brand",
    "cmo",
    "trade marketing",
    "chief marketing",
)

CONCERT_NONPROFIT_NAME_SUBSTRINGS = (
    "foundation",
    "friends of",
    "alliance",
    "coalition",
    "chamber of commerce",
)


def concert_title_gate(title: str) -> Tuple[bool, str]:
    t = (title or "").strip().lower()
    if not t:
        return False, "empty_title"
    for b in CONCERT_TITLE_BLOCK_SUBSTRINGS:
        if b in t:
            return False, f"title_blocked:{b.strip()}"
    if not any(a in t for a in CONCERT_TITLE_ALLOW_SUBSTRINGS):
        return False, "title_not_relevant"
    has_collab = any(c in t for c in _COLLAB_ALONE_SUBSTRINGS)
    has_paid = any(p in t for p in _PAID_TITLE_CONTEXT)
    if has_collab and not has_paid:
        return False, "title_collab_not_paid"
    return True, "ok"


def concert_email_ok(email: str, monday_emails: Set[str]) -> Tuple[bool, str]:
    email_n = normalize_email(email)
    if not email_n:
        return False, "no email"
    bad = email_blocked(email_n)
    if bad:
        return False, f"email QA: {bad}"
    if email_n in monday_emails:
        return False, f"email already on Monday ({email_n})"
    return True, "ok"


def concert_protected_account_blocked(
    *,
    org_name: str,
    website: str = "",
    email: str = "",
    protected_names: Set[str],
    protected_domains: Set[str],
) -> Optional[str]:
    """
    Skip if this company or its domain is already in a live conversation / closed deal.
    Returns a reason string or None if ok.
    """
    nk = normalize_company_key(org_name)
    crm_norms = set(protected_names)
    crm_lower = set(protected_names)
    if nk and company_collides_with_crm(org_name, crm_lower, crm_norms):
        return f"protected_company:{nk}"

    site = website_domain_key(website)
    if site and site in protected_domains:
        return f"protected_domain:{site}"

    em_dom = email_domain_key(email)
    if em_dom and not is_personal_email_domain(em_dom) and em_dom in protected_domains:
        return f"protected_domain:{em_dom}"

    return None


def concert_blacklist_blocked(org_name: str, forbidden_names: Set[str]) -> Optional[str]:
    if not forbidden_names:
        return None
    crm_lower = {str(x).strip().lower() for x in forbidden_names if str(x).strip()}
    crm_norms = {normalize_company_key(x) for x in crm_lower}
    crm_norms.discard("")
    if company_collides_with_crm(org_name, crm_lower, crm_norms):
        return f"blacklist:{normalize_company_key(org_name)}"
    return None


def concert_nonprofit_name_blocked(org_name: str) -> Optional[str]:
    n = (org_name or "").strip().lower()
    if not n:
        return None
    for sub in CONCERT_NONPROFIT_NAME_SUBSTRINGS:
        if sub in n:
            return f"concert_nonprofit:{sub.strip()}"
    return None


def contact_location(person: dict[str, Any], enriched: Optional[dict[str, Any]] = None) -> Tuple[str, str, str]:
    """Person city, state, and country. Company HQ must not overwrite where the contact lives."""
    enriched = enriched or {}
    city = (enriched.get("city") or person.get("city") or "").strip()
    state = (enriched.get("state") or person.get("state") or "").strip()
    country = (enriched.get("country") or person.get("country") or "").strip()
    return city, state, country


def concert_org_name(person: dict[str, Any], enriched: Optional[dict[str, Any]] = None) -> str:
    org = (enriched or {}).get("organization") or person.get("organization") or {}
    return org.get("name", "") or person.get("organization_name", "") or "Unknown"


def concert_org_viable(
    *,
    org_name: str,
    org_industry: str,
    email: str = "",
    annual_revenue: Any = None,
    estimated_employees: Any = None,
    min_revenue: Optional[int] = None,
    min_employees: Optional[int] = None,
    strict: Optional[bool] = None,
) -> Tuple[bool, str]:
    """
    Reuse sponsor firmographic gates in brand mode ($10M floor) plus concert
    nonprofit-name and employee floor. min_revenue / min_employees override the
    CONCERT_MIN_ORG_* env defaults for a run.
    """
    np = concert_nonprofit_name_blocked(org_name)
    if np:
        return False, np

    bad_name = org_name_blocked(org_name)
    if bad_name:
        return False, bad_name

    bad_ind = org_industry_blocked(org_industry)
    if bad_ind:
        return False, bad_ind

    ok, reason = sponsor_org_viable(
        org_name=org_name,
        org_industry=org_industry,
        email=email,
        annual_revenue=annual_revenue,
        estimated_employees=estimated_employees,
        brand_mode=True,
        strict=strict,
        min_revenue=min_revenue,
        min_employees=min_employees,
    )
    if not ok:
        return False, reason

    min_rev = concert_min_org_revenue() if min_revenue is None else int(min_revenue)
    rev = parse_annual_revenue_usd(annual_revenue)
    if rev is not None and min_rev > 0 and rev < min_rev:
        return False, f"revenue_below_min:{rev}<{min_rev}"

    min_emp = concert_min_org_employees() if min_employees is None else int(min_employees)
    if min_emp > 0 and estimated_employees is not None and str(estimated_employees).strip() != "":
        try:
            emp = int(estimated_employees)
            if emp < min_emp:
                return False, f"employees_below_min:{emp}"
        except (TypeError, ValueError):
            pass

    return True, "ok"


def normalize_person_id(person: dict) -> Optional[str]:
    pid = person.get("id") or person.get("apollo_id")
    if not pid:
        return None
    return str(pid)
