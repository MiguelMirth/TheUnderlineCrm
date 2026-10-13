"""
Prospecting QA: geography, titles, trash patterns, Monday email dedupe, CRM collision.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional, Tuple

# Universities / academic medical — not sponsorship targets (audit + Lia review)
UNIVERSITY_ORG_BLOCK_SUBSTRINGS = [
    "university",
    " college",
    "college of",
    "state university",
    "institute of technology",
    "institute of",
    "culinary institute",
    "school of medicine",
    "academic medical",
    "university of ",
]

# --- Org / company "trash" heuristics (substring match on org name, lowercased) ---
ORG_NAME_BLOCK_SUBSTRINGS = [
    " fc",
    " c.f.",
    "football club",
    "soccer club",
    "rugby club",
    " cricket ",
    "nfl ",
    " nba ",
    " mlb ",
    " nhl ",
    " ncaa",
    "athletic department",
    "minor league",
    "premier league",
    "bundesliga",
    "serie a",
    "olympic team",
    "national team",
]

# Substrings in organization.industry (lowercased) — block obvious misfits
ORG_INDUSTRY_BLOCK_SUBSTRINGS = [
    "spectator sports",
    "sports team",
    "college",
    "professional training",
    "e-learning providers",
    "higher education",
    "education management",
    "government administration",
    "legislative office",
    "public policy",
    "law enforcement",
    "military",
    "civic & social organization",
    "think tanks",
    # Agencies, consultancies, research — not sponsorship buyers (Numerator, Epsilon, Fractal)
    "market research",
    "marketing & advertising",
    "marketing and advertising",
    "management consulting",
    "public relations",
    "staffing & recruiting",
    "staffing and recruiting",
    "human resources",
    "information technology & services",
    "mechanical or industrial engineering",
    "electrical/electronic manufacturing",
    "venture capital",
    "private equity",
    "investment management",
    "legal services",
    "accounting",
    "philanthropy",
    "fund-raising",
    "fundraising",
]

# Apollo industries that plausibly sponsor consumer / experiential activations
ORG_INDUSTRY_SPONSOR_ALLOW_SUBSTRINGS = [
    "food",
    "beverage",
    "wine",
    "spirits",
    "consumer goods",
    "consumer packaged",
    "restaurant",
    "grocery",
    "retail",
    "entertainment",
    "cosmetics",
    "leisure",
    "hospitality",
    "wellness",
    "food production",
    "food & beverages",
    "wholesale",  # large beverage distributors (Reyes, Southern Glazer's)
    "luxury goods",
    "apparel",
    "sporting goods",
    # Underline big-fish verticals (Brickell banks, fitness, healthcare systems)
    "banking",
    "bank",
    "financial services",
    "finance",
    "insurance",
    "health",
    "hospital",
    "fitness",
    "recreation",
    "sports",
]

# Org names that are never Underline sponsors (services firms)
NON_SPONSOR_ORG_NAME_SUBSTRINGS = [
    "numerator",
    "epsilon",
    "fractal.ai",
    "fractal ",
    "market research",
    "syndicated research",
    "advertising agency",
    " ad agency",
    "media agency",
    "consulting group",
    "management consulting",
    "gartner",
    "forrester",
    "kantar",
    "nielsen",
    "iqvia",
    "ipsos",
    "mckinsey",
    "boston consulting",
    "deloitte consulting",
    "accenture",
    "publicis",
    "omnicom",
    "wpp ",
    "dentsu",
]

# Federal / public health agencies — not event sponsors (audit: SAMHSA, HRSA, NIH, etc.)
FEDERAL_ORG_NAME_BLOCK_SUBSTRINGS = [
    "samhsa",
    "hrsa",
    " nih",
    "nih ",
    "national institutes of health",
    "national institute of",
    "nimh",
    "nci ",
    " nci",
    "niams",
    "ninr",
    "nida",
    "cdc ",
    " cdc",
    "centers for disease control",
    "food and drug administration",
    " indian health service",
    "centers for medicare",
    "cms ",
    "medicare & medicaid",
    "medicaid services",
    "health resources and services administration",
    "substance abuse and mental health services administration",
    "substance abuse and mental health",
    "u.s. department of health",
    "department of health and human services",
    "department of health",
    "health and human services",
    "veterans affairs",
    "va medical center",
    "public health service",
    "county health department",
    "state health department",
    "regional health department",
    "federal division",
    "administration (hhs)",
    "acf.hhs",
]

# Generic / non-sponsor healthcare org descriptors (not branded hospital systems)
NON_SPONSOR_HEALTHCARE_ORG_SUBSTRINGS = [
    "mental health clinic",
    "mental health clinics",
    "diagnostic center",
    "diagnostic centers",
    "rehabilitation center",
    "rehab center",
    "urgent care center",
    "community health center",
    "federally qualified health",
    "fqhc",
    "physician group",
    "medical group practice",
    "clinical research organization",
]

# Hospital / payer / medtech brands that *can* sponsor — do not block if name matches
HEALTHCARE_SPONSOR_ALLOW_SUBSTRINGS = [
    "baptist health",
    "jackson health",
    "nicklaus",
    "tenethealth",
    "tenet health",
    "hca healthcare",
    "broward health",
    "florida blue",
    "cleveland clinic",
    "mayo clinic",
    "mount sinai",
    "adventhealth",
    "memorial healthcare",
    "holycross health",
    "unitedhealth",
    "elevance health",
    "anthem",
    "aetna",
    "cigna",
    "humana",
    "molina healthcare",
    "molina health",
    "cvs health",
    "walgreens",
    "ge healthcare",
    "ge health",
    "philips healthcare",
    "johnson & johnson",
    "pfizer",
    "novartis",
    "roche",
    "american heart",
    "health-ade",
    "guardant health",
    "teladoc",
    "cano health",
    "sutter health",
    "novant health",
    "baptist",
    "florida health",
    "south florida baptist",
]

# Email domains that must never enter prospecting
EMAIL_DOMAIN_BLOCK_SUFFIXES = (
    ".gov",
    ".mil",
    ".gov.uk",
    ".edu",
)
EMAIL_DOMAIN_BLOCK_EXACT = frozenset(
    {
        "mail.nih.gov",
        "samhsa.gov",
        "samhsa.hhs.gov",
        "hrsa.gov",
        "nih.gov",
        "hhs.gov",
        "cdc.gov",
        "fda.gov",
        "va.gov",
        "cms.gov",
    }
)

# Title must match at least one of these (substring, lowercased)
TITLE_ALLOW_SUBSTRINGS = [
    "sponsor",
    "sponsorship",
    "partner",
    "partnership",
    "brand",
    "marketing",
    "communications",
    "cmo",
    "chief marketing",
    "vp",
    "vice president",
    "president",
    "ceo",
    "founder",
    "director",
    "head of",
    "experiential",
    "events",
    "community",
    "corporate affairs",
    "public affairs",
    "customer experience",
    "cx ",
    "integrated marketing",
    "growth",
]

# C-suite / board — unlikely to reply; sponsorship desks are director/VP marketing
TITLE_EXEC_BLOCK_SUBSTRINGS = [
    "chief executive",
    "chairman",
    "chairwoman",
    " cfo",
    "cfo ",
    "chief financial",
    "chief operating",
    "coo ",
    " general counsel",
    "board member",
    "board of directors",
]

# Block junior / irrelevant roles even if a token above appears
TITLE_BLOCK_SUBSTRINGS = [
    "intern",
    "coordinator",
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
    "coach",
    "athletic director",
    "equipment manager",
    "store manager",
    "assistant store",
    "shift manager",
    "staffing",
    "privacy",
    "data security",
    "information security",
    " grc",
    "internal audit",
    "director of operations",
    "vp of sales",
    "vice president of sales",
    "director of sales",
    "regional sales",
    "sales director",
    "sr director sales",
    "senior director of sales",
    "vp of sales",
    "director, privacy",
    "director of finance",
    "director, finance",
    " fp&a",
    "fp&a ",
    "financial planning",
    "controller",
    "accounting",
    "procurement",
]

# Sales/ops titles allowed only when sponsorship-facing language is present
TITLE_SPONSOR_CONTEXT_MARKERS = (
    "sponsor",
    "partnership",
    "brand",
    "experiential",
    "events",
    "trade marketing",
    "field marketing",
    "community",
    "activation",
)

US_COUNTRY_TOKENS = frozenset(
    {
        "united states",
        "usa",
        "u.s.",
        "u.s.a.",
        "us",
    }
)

FL_STATE_TOKENS = frozenset({"fl", "florida"})

SOUTH_US_STATE_TOKENS = frozenset(
    {
        "ga",
        "georgia",
        "tx",
        "texas",
        "tn",
        "tennessee",
        "nc",
        "north carolina",
        "sc",
        "south carolina",
        "la",
        "louisiana",
        "al",
        "alabama",
        "ms",
        "mississippi",
        "ar",
        "arkansas",
    }
)

# Cities / regions treated as strong Underline adjacency (substring in city, lowercased)
SOUTH_FLORIDA_CITY_HINTS = (
    "miami",
    "fort lauderdale",
    "hollywood",
    "pembroke pines",
    "hialeah",
    "coral gables",
    "doral",
    "aventura",
    "kendall",
    "brickell",
    "coconut grove",
    "miami beach",
    "surfside",
    "homestead",
    "cutler bay",
    "palmetto bay",
    "boca raton",
    "west palm",
    "palm beach",
    "delray",
    "deerfield",
    "plantation",
    "sunrise",
    "miramar",
)


def normalize_email(raw: str) -> str:
    return re.sub(r"\s+", "", (raw or "").strip().lower())


def normalize_company_key(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"[\.,'\u2019]+", "", s)
    s = re.sub(r"\b(inc|llc|ltd|corp|corporation|co|company|plc|sa|ag)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def company_collides_with_crm(
    company_name: str,
    crm_lower: set[str],
    crm_norms: set[str],
) -> bool:
    """True if this brand is already represented on the CRM / forbidden list."""
    nl = company_name.strip().lower()
    if not nl:
        return True
    nk = normalize_company_key(company_name)
    if not nk:
        return True
    if nl in crm_lower:
        return True
    if nk in crm_norms:
        return True
    for cn in crm_norms:
        if cn == nk:
            return True
        if len(cn) >= 10 and len(nk) >= 10 and (cn in nk or nk in cn):
            return True
        if len(nk) >= 6 and len(cn) > len(nk) and cn.startswith(nk + " "):
            return True
        if len(cn) >= 6 and len(nk) > len(cn) and nk.startswith(cn + " "):
            return True
    return False


def parse_email_column_value(cv: Dict[str, Any]) -> str:
    """Monday email column: prefer text; else JSON value."""
    t = (cv.get("text") or "").strip()
    if t:
        return t
    raw = cv.get("value")
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return str(raw).strip()
    if isinstance(data, dict):
        return (data.get("email") or data.get("text") or "").strip()
    return ""


# Concert Series (and similar volume lanes): do not re-touch companies already
# in a live conversation or closed deal. Groups + lead-status labels on the
# Underline master board.
PROTECTED_GROUP_IDS = frozenset(
    {
        "group_mm0xj5rd",  # Engaged / Replied
        "group_mm0xj1qw",  # Meeting / Pipeline
        "group_mm0xnfca",  # Closed Won
    }
)
PROTECTED_STATUS_LABELS = frozenset(
    {
        "replied",
        "meeting set",
        "proposal sent",
    }
)
PERSONAL_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "yahoo.co.uk",
        "hotmail.com",
        "outlook.com",
        "live.com",
        "msn.com",
        "icloud.com",
        "me.com",
        "mac.com",
        "aol.com",
        "protonmail.com",
        "proton.me",
        "ymail.com",
        "comcast.net",
        "att.net",
        "sbcglobal.net",
        "verizon.net",
        "bellsouth.net",
    }
)
COL_WEBSITE = "text_mm0xt1wm"
COL_LEAD_STATUS = "status"


def is_personal_email_domain(domain: str) -> bool:
    return _domain_key_simple(domain) in PERSONAL_EMAIL_DOMAINS


def item_is_protected(*, group_id: str, status: str) -> bool:
    gid = (group_id or "").strip()
    st = (status or "").strip().lower()
    if gid in PROTECTED_GROUP_IDS:
        return True
    return st in PROTECTED_STATUS_LABELS


def email_domain_key(email: str) -> str:
    e = normalize_email(email)
    if "@" not in e:
        return ""
    return e.split("@", 1)[1]



def _country_is_us(country: str) -> bool:
    c = (country or "").strip().lower()
    if not c:
        return False
    if c in US_COUNTRY_TOKENS:
        return True
    return "united states" in c


def _state_is_florida(state: str) -> bool:
    s = (state or "").strip().lower()
    if not s:
        return False
    if s in FL_STATE_TOKENS:
        return True
    return "florida" in s


def _city_south_fl_hint(city: str) -> bool:
    c = (city or "").strip().lower()
    if not c:
        return False
    return any(h in c for h in SOUTH_FLORIDA_CITY_HINTS)


def person_in_florida(person: Dict[str, Any]) -> bool:
    p_city = (person.get("city") or "").strip()
    p_state = (person.get("state") or "").strip()
    # A filled non-Florida state wins. "Hollywood" must not match West Hollywood, California.
    if p_state and not _state_is_florida(p_state):
        return False
    return _state_is_florida(p_state) or _city_south_fl_hint(p_city)


def _state_is_south_us(state: str) -> bool:
    s = (state or "").strip().lower()
    if not s:
        return False
    if s in SOUTH_US_STATE_TOKENS:
        return True
    return any(tok in s for tok in ("georgia", "texas", "tennessee", "carolina", "louisiana", "alabama"))


def person_geo_tier(person: Dict[str, Any]) -> Tuple[int, str]:
    """
    Score person geography for Underline outreach (higher = better).
    3 = Miami / South FL metro, 2 = FL state or southern US, 1 = other US, 0 = non-US.
    """
    p_city = (person.get("city") or "").strip()
    p_state = (person.get("state") or "").strip()
    p_country = (person.get("country") or "").strip()

    if p_country and not _country_is_us(p_country):
        return 0, "non_us_person"

    if _city_south_fl_hint(p_city):
        return 3, "south_florida_metro"

    if _state_is_florida(p_state):
        return 2, "florida_state"

    if _state_is_south_us(p_state):
        return 2, "south_us"

    if p_country and _country_is_us(p_country):
        return 1, "us_person"

    if p_state or p_city:
        return 1, "us_person_partial"

    return 0, "location_unknown"


def geo_person_org_gate(
    person: Dict[str, Any],
    org: Dict[str, Any],
    *,
    require_us: bool,
    require_florida: bool,
    person_florida_only: bool = True,
    allow_global_org: bool = True,
) -> Tuple[bool, str]:
    """
    require_us: non-US person country fails. Org may be global when allow_global_org=True.
    require_florida + person_florida_only: contact must live/work in Florida (org HQ ignored).
    Legacy require_florida without person_florida_only: person OR org South FL / Florida signals.
    """
    p_city = (person.get("city") or "").strip()
    p_state = (person.get("state") or "").strip()
    p_country = (person.get("country") or "").strip()

    o_city = (org.get("city") or "").strip()
    o_state = (org.get("state") or "").strip()
    o_country = (org.get("country") or "").strip()

    if require_us:
        if p_country and not _country_is_us(p_country):
            return False, f"person_country_not_us:{p_country}"
        if not allow_global_org:
            if not o_country or not _country_is_us(o_country):
                return False, f"org_country_not_us:{o_country or 'unknown'}"

    if require_florida:
        if person_florida_only:
            if not person_in_florida(person):
                return False, f"person_not_florida:{p_city}|{p_state}"
        else:
            fl_ok = (
                _state_is_florida(p_state)
                or _state_is_florida(o_state)
                or _city_south_fl_hint(p_city)
                or _city_south_fl_hint(o_city)
            )
            if not fl_ok:
                return False, f"not_florida_area:{p_city}|{p_state}|{o_city}|{o_state}"

    return True, "ok"


def _healthcare_org_is_allowlisted(org_name_lower: str) -> bool:
    return any(a in org_name_lower for a in HEALTHCARE_SPONSOR_ALLOW_SUBSTRINGS)


def university_org_blocked(org_name: str) -> Optional[str]:
    n = (org_name or "").strip().lower()
    if not n:
        return None
    for sub in UNIVERSITY_ORG_BLOCK_SUBSTRINGS:
        if sub in n:
            return f"university_org_block:{sub.strip()}"
    return None


def out_of_market_hospital_blocked(
    org_name: str,
    org_state: str = "",
    org_city: str = "",
) -> Optional[str]:
    """
    Block academic / regional hospital systems outside Florida (e.g. Boston Children's, NY Presbyterian).
    Sponsor-capable FL systems remain allowlisted in HEALTHCARE_SPONSOR_ALLOW_SUBSTRINGS.
    """
    n = (org_name or "").strip().lower()
    if not n or _healthcare_org_is_allowlisted(n):
        return None
    hospitalish = any(
        x in n
        for x in (
            "hospital",
            "medical center",
            "health system",
            "children's",
            "presbyterian",
            "memorial hospital",
            "clinic",
            "healthcare partners",
        )
    )
    if not hospitalish:
        return None
    if _state_is_florida(org_state) or _city_south_fl_hint(org_city):
        return None
    return "hospital_out_of_market"


def federal_or_public_health_org_blocked(org_name: str) -> Optional[str]:
    n = (org_name or "").strip().lower()
    if not n:
        return None
    for sub in FEDERAL_ORG_NAME_BLOCK_SUBSTRINGS:
        if sub in n:
            return f"federal_org_block:{sub.strip()}"
    return None


def non_sponsor_healthcare_org_blocked(org_name: str) -> Optional[str]:
    """
    Block generic clinics and broad 'health' orgs that are not sponsor-capable brands.
    Allowlisted hospital systems / payers / medtech pass through.
    """
    n = (org_name or "").strip().lower()
    if not n:
        return None
    if _healthcare_org_is_allowlisted(n):
        return None
    for sub in NON_SPONSOR_HEALTHCARE_ORG_SUBSTRINGS:
        if sub in n:
            return f"healthcare_nonsponsor_block:{sub.strip()}"
    # Broad public-sector / agency phrasing in a health-sounding name
    if any(
        x in n
        for x in (
            "services administration",
            "health administration",
            "national institute",
            "federal ",
            " u.s. ",
            "united states department",
        )
    ):
        return "healthcare_nonsponsor_block:public_agency_phrase"
    return None


def email_blocked(email: str) -> Optional[str]:
    """Block .gov / federal health inboxes from prospecting."""
    e = normalize_email(email)
    if not e or "@" not in e:
        return None
    domain = e.split("@", 1)[1]
    if domain in EMAIL_DOMAIN_BLOCK_EXACT:
        return f"email_domain_block:{domain}"
    for suffix in EMAIL_DOMAIN_BLOCK_SUFFIXES:
        if domain.endswith(suffix):
            return f"email_domain_block:{domain}"
    # Subdomains like samhsa.hhs.gov, mail.nih.gov
    if ".gov" in domain or domain.endswith(".hhs.gov"):
        return f"email_domain_block:{domain}"
    return None


def org_name_blocked(org_name: str) -> Optional[str]:
    n = (org_name or "").strip().lower()
    if not n:
        return None
    uni = university_org_blocked(org_name)
    if uni:
        return uni
    fed = federal_or_public_health_org_blocked(org_name)
    if fed:
        return fed
    health = non_sponsor_healthcare_org_blocked(org_name)
    if health:
        return health
    for sub in ORG_NAME_BLOCK_SUBSTRINGS:
        if sub in n:
            return f"org_name_block:{sub.strip()}"
    return None


def _domain_key_simple(domain: str) -> str:
    d = (domain or "").strip().lower()
    d = d.replace("https://", "").replace("http://", "")
    return d.split("/")[0].removeprefix("www.")


def website_domain_key(domain: str) -> str:
    """Public alias for host extraction from a URL or domain."""
    return _domain_key_simple(domain)


def org_industry_blocked_for_brand(
    industry: str,
    *,
    shelf_brand: str,
    org: Dict[str, Any],
    brand_domain: str = "",
) -> Optional[str]:
    """
    Apollo often tags consumer brands with junk industries (EARgasm, Neutrogena).
    Trust the brand's official domain on the org record.
    """
    blocked = org_industry_blocked(industry)
    if not blocked or not shelf_brand:
        return blocked
    try:
        from apollo_brand_domains import guess_brand_domains
    except ImportError:
        return blocked
    org_dom = _domain_key_simple(
        org.get("primary_domain") or org.get("website_url") or org.get("domain") or ""
    )
    trusted = {_domain_key_simple(d) for d in guess_brand_domains(shelf_brand)}
    if brand_domain:
        trusted.add(_domain_key_simple(brand_domain))
    if org_dom and org_dom in trusted:
        return None
    return blocked


def org_industry_blocked(industry: str) -> Optional[str]:
    ind = (industry or "").strip().lower()
    if not ind:
        return None
    for sub in ORG_INDUSTRY_BLOCK_SUBSTRINGS:
        if sub in ind:
            return f"industry_block:{sub}"
    return None


def non_sponsor_org_name_blocked(org_name: str) -> Optional[str]:
    n = (org_name or "").strip().lower()
    if not n:
        return None
    for sub in NON_SPONSOR_ORG_NAME_SUBSTRINGS:
        if sub in n:
            return f"non_sponsor_org:{sub.strip()}"
    if re.search(r"\b(agency|consultancy|consulting firm)\b", n):
        if not any(x in n for x in ("brand", "partnership", "sponsorship")):
            return "non_sponsor_org:agency_or_consultancy"
    return None


def org_industry_sponsor_allowed(industry: str) -> bool:
    ind = (industry or "").strip().lower()
    if not ind:
        return False
    return any(a in ind for a in ORG_INDUSTRY_SPONSOR_ALLOW_SUBSTRINGS)


def parse_annual_revenue_usd(raw: Any) -> Optional[int]:
    """Parse Apollo/Monda revenue fields to integer USD (None if unknown)."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    s = str(raw).strip().lower().replace(",", "").replace("$", "")
    if not s:
        return None
    mult = 1
    if s.endswith("k"):
        mult = 1_000
        s = s[:-1]
    elif s.endswith("m"):
        mult = 1_000_000
        s = s[:-1]
    elif s.endswith("b"):
        mult = 1_000_000_000
        s = s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return None


def sponsor_org_viable(
    *,
    org_name: str,
    org_industry: str,
    email: str = "",
    annual_revenue: Any = None,
    estimated_employees: Any = None,
    brand_mode: bool = False,
    shared_employer: bool = False,
    shelf_brand_name: str = "",
    strict: Optional[bool] = None,
    min_revenue: Optional[int] = None,
    min_employees: Optional[int] = None,
) -> Tuple[bool, str]:
    """
    Strict gate: keep orgs that can realistically sponsor The Underline (big consumer / experiential brands).

    Defaults read PROSPECT_SPONSOR_STRICT, the brand or standard revenue floor, and PROSPECT_MIN_ORG_EMPLOYEES
    at call time. The engine passes strict=True and per-run floors, so a run never mutates os.environ.
    """
    strict_on = strict if strict is not None else os.getenv("PROSPECT_SPONSOR_STRICT", "true").lower() == "true"
    if not strict_on:
        return True, "ok"

    brand_mode = brand_mode or os.getenv("PROSPECT_BRAND_MODE", "false").lower() == "true"

    em = normalize_email(email)
    if em.endswith(".edu"):
        return False, "email_edu"

    bad_name = non_sponsor_org_name_blocked(org_name)
    if bad_name:
        return False, bad_name

    from brand_targeting import is_beverage_distributor_or_wholesaler

    if is_beverage_distributor_or_wholesaler(org_name, org_industry):
        return False, "distributor_wholesaler"

    rev = parse_annual_revenue_usd(annual_revenue)
    industry_ok = org_industry_sponsor_allowed(org_industry)

    # Brand runs: parent employers (PepsiCo for Lay's) — skip revenue on shared employer;
    # still block junk industries. Standalone brand orgs use lower floor ($10M default).
    if brand_mode and shared_employer:
        if org_industry_blocked(org_industry):
            return False, f"industry_block_shared:{org_industry or 'unknown'}"
        return True, "ok"

    if min_revenue is not None:
        min_rev = int(min_revenue)
    elif brand_mode:
        min_rev = int(os.getenv("PROSPECT_BRAND_MIN_ORG_REVENUE", "10000000"))
    else:
        min_rev = int(os.getenv("PROSPECT_MIN_ORG_REVENUE", "100000000"))

    if rev is not None and rev < min_rev:
        soft_ok = brand_mode and industry_ok and rev >= (min_rev // 2)
        if not soft_ok:
            return False, f"revenue_below_min:{rev}<{min_rev}"

    if not industry_ok:
        if rev is None:
            return False, f"industry_not_sponsor_capable:{org_industry or 'unknown'}"
        if rev < min_rev * 2:
            return False, f"industry_not_sponsor_capable:{org_industry or 'unknown'}"

    min_emp = int(min_employees) if min_employees is not None else int(os.getenv("PROSPECT_MIN_ORG_EMPLOYEES", "0"))
    if min_emp > 0 and estimated_employees is not None:
        try:
            emp = int(estimated_employees)
            if emp < min_emp:
                return False, f"employees_below_min:{emp}"
        except (TypeError, ValueError):
            pass

    return True, "ok"


def _title_is_c_suite_executive(t: str) -> Optional[str]:
    """CEO / chairman / etc. Allow VP and sponsorship-labeled presidents."""
    if "vice president" in t or " vp " in t or t.startswith("vp "):
        return None
    for marker in ("sponsorship", "partnership", "brand", "marketing", "community", "experiential", "events"):
        if marker in t and "president" in t:
            return None
    for b in TITLE_EXEC_BLOCK_SUBSTRINGS:
        if b in t:
            return f"title_blocked:{b.strip()}"
    if re.search(r"\bceo\b", t):
        return "title_blocked:ceo"
    if "founder" in t and not any(m in t for m in ("sponsorship", "partnership", "brand marketing")):
        return "title_blocked:founder"
    if "president" in t:
        return "title_blocked:president"
    return None


def title_gate(title: str) -> Tuple[bool, str]:
    t = (title or "").strip().lower()
    if not t:
        return False, "empty_title"
    exec_block = _title_is_c_suite_executive(t)
    if exec_block:
        return False, exec_block
    for b in TITLE_BLOCK_SUBSTRINGS:
        if b in t:
            return False, f"title_blocked:{b.strip()}"
    if not any(a in t for a in TITLE_ALLOW_SUBSTRINGS):
        return False, "title_not_relevant"
    ok_ctx, ctx_reason = title_sponsor_context_gate(t)
    if not ok_ctx:
        return False, ctx_reason
    return True, "ok"


def title_sponsor_context_gate(title_lower: str) -> Tuple[bool, str]:
    """Reject sales/ops/store titles unless sponsorship/brand context appears."""
    t = title_lower
    ambiguous = (
        "sales",
        "operations",
        "business director",
        "analytics",
        "business development",
        "fp&a",
        "finance",
    )
    if any(a in t for a in ambiguous):
        if not any(m in t for m in TITLE_SPONSOR_CONTEXT_MARKERS):
            return False, "title_blocked:sales_or_ops_without_sponsor_context"
    return True, "ok"
