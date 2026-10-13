"""
Underline prospecting = **consumer brands on the shelf**, not corporate holding companies.

Lia direction (2026-05): Anheuser-Busch InBev / The Wonderful Company are not the sponsor;
the **brand** (Budweiser, Fiji Water, Wonderful Pistachios) is.
"""
from __future__ import annotations

import json

from prospecting_qa import normalize_company_key

# Monday / Gemini targets that are holding companies — reject for brand-first prospecting.
CORPORATE_HOLDING_KEYS = {
    normalize_company_key(x)
    for x in (
        "Anheuser-Busch InBev",
        "Anheuser-Busch",
        "AB InBev",
        "The Coca-Cola Company",
        "Coca-Cola Company",
        "PepsiCo",
        "PepsiCo Inc",
        "Unilever",
        "Unilever PLC",
        "LVMH",
        "LVMH Moet Hennessy Louis Vuitton",
        "Pernod Ricard",
        "Procter & Gamble",
        "P&G",
        "The Wonderful Company",
        "Wonderful Company",
        "Nestle",
        "Nestlé",
        "General Mills",
        "Kraft Heinz",
        "Kraft Heinz Company",
        "Diageo",
        "Constellation Brands",
        "Brown-Forman",
        "Molson Coors",
        "Heineken",
        "Heineken USA",
        "Keurig Dr Pepper",
        "JBS USA",
        "Tyson Foods",
        "Tyson Foods Inc",
        "Smithfield Foods",
        "Conagra Brands",
        "Mondelez International",
        "Mondelēz",
        "Campbell Soup Company",
        "Hormel Foods",
    )
}

# Apollo often lists US marketers under the US operating company, not the brand microsite.
# Monday row = shelf brand; Apollo search = employer hint below.
BRAND_APOLLO_EMPLOYER: dict[str, dict[str, str]] = {
    normalize_company_key("Budweiser"): {
        "apollo_search_name": "Anheuser-Busch",
        "domain": "anheuser-busch.com",
        "employer_only": "true",
    },
    normalize_company_key("Michelob ULTRA"): {
        "apollo_search_name": "Anheuser-Busch",
        "domain": "anheuser-busch.com",
        "employer_only": "true",
    },
    normalize_company_key("Michelob Ultra"): {
        "apollo_search_name": "Anheuser-Busch",
        "domain": "anheuser-busch.com",
        "employer_only": "true",
    },
    normalize_company_key("Modelo"): {
        "apollo_search_name": "Constellation Brands",
        "domain": "cbrands.com",
        "employer_only": "true",
    },
    normalize_company_key("Corona"): {
        "apollo_search_name": "Constellation Brands",
        "domain": "cbrands.com",
        "employer_only": "true",
    },
    normalize_company_key("Corona Extra"): {
        "apollo_search_name": "Constellation Brands",
        "domain": "cbrands.com",
        "employer_only": "true",
    },
    normalize_company_key("Pepsi"): {
        "apollo_search_name": "PepsiCo",
        "domain": "pepsico.com",
        "employer_only": "true",
    },
    normalize_company_key("Mountain Dew"): {
        "apollo_search_name": "PepsiCo",
        "domain": "pepsico.com",
        "employer_only": "true",
    },
    normalize_company_key("Gatorade"): {
        "apollo_search_name": "PepsiCo",
        "domain": "pepsico.com",
        "employer_only": "true",
    },
    normalize_company_key("Doritos"): {
        "apollo_search_name": "PepsiCo",
        "domain": "pepsico.com",
        "employer_only": "true",
    },
    normalize_company_key("Oreo"): {
        "apollo_search_name": "Mondelez International",
        "domain": "mondelezinternational.com",
        "employer_only": "true",
    },
    normalize_company_key("Clif Bar"): {
        "apollo_search_name": "Mondelez International",
        "domain": "mondelezinternational.com",
        "employer_only": "true",
    },
    normalize_company_key("Jack Daniel's"): {
        "apollo_search_name": "Brown-Forman",
        "domain": "brown-forman.com",
        "employer_only": "true",
    },
    normalize_company_key("Patron"): {
        "apollo_search_name": "Bacardi",
        "domain": "bacardi.com",
        "employer_only": "true",
    },
    normalize_company_key("Grey Goose"): {
        "apollo_search_name": "Bacardi",
        "domain": "bacardi.com",
        "employer_only": "true",
    },
    normalize_company_key("Perrier"): {
        "apollo_search_name": "Nestlé",
        "domain": "nestle.com",
        "employer_only": "true",
    },
    normalize_company_key("Hennessy"): {
        "apollo_search_name": "Moët Hennessy",
        "domain": "lvmh.com",
        "employer_only": "true",
    },
    normalize_company_key("Absolut"): {
        "apollo_search_name": "Pernod Ricard",
        "domain": "pernod-ricard.com",
        "employer_only": "true",
    },
    normalize_company_key("Smirnoff"): {
        "apollo_search_name": "Diageo",
        "domain": "diageo.com",
        "employer_only": "true",
    },
    normalize_company_key("Ciroc"): {
        "apollo_search_name": "Diageo",
        "domain": "diageo.com",
        "employer_only": "true",
    },
    normalize_company_key("CÎROC"): {
        "apollo_search_name": "Diageo",
        "domain": "diageo.com",
        "employer_only": "true",
    },
    normalize_company_key("Lacoste"): {
        "apollo_search_name": "Lacoste",
        "domain": "lacoste.com",
        "employer_only": "true",
    },
    normalize_company_key("BeatBox Beverages"): {
        "apollo_search_name": "BeatBox",
        "domain": "beatboxbeverages.com",
        "employer_only": "false",
    },
    normalize_company_key("Sprite"): {
        "apollo_search_name": "PepsiCo",
        "domain": "pepsico.com",
        "employer_only": "true",
    },
    normalize_company_key("Tropicana"): {
        "apollo_search_name": "PepsiCo",
        "domain": "pepsico.com",
        "employer_only": "true",
    },
    normalize_company_key("Naked Juice"): {
        "apollo_search_name": "PepsiCo",
        "domain": "pepsico.com",
        "employer_only": "true",
    },
    normalize_company_key("Snapple"): {
        "apollo_search_name": "Keurig Dr Pepper",
        "domain": "keurigdrpepper.com",
        "employer_only": "true",
    },
    normalize_company_key("Dr Pepper"): {
        "apollo_search_name": "Keurig Dr Pepper",
        "domain": "keurigdrpepper.com",
        "employer_only": "true",
    },
    normalize_company_key("Simply Beverages"): {
        "apollo_search_name": "The Coca-Cola Company",
        "domain": "coca-cola.com",
        "employer_only": "true",
    },
    normalize_company_key("Smartwater"): {
        "apollo_search_name": "The Coca-Cola Company",
        "domain": "coca-cola.com",
        "employer_only": "true",
    },
    normalize_company_key("Vitaminwater"): {
        "apollo_search_name": "The Coca-Cola Company",
        "domain": "coca-cola.com",
        "employer_only": "true",
    },
    normalize_company_key("Captain Morgan"): {
        "apollo_search_name": "Diageo",
        "domain": "diageo.com",
        "employer_only": "true",
    },
    normalize_company_key("Crown Royal"): {
        "apollo_search_name": "Diageo",
        "domain": "diageo.com",
        "employer_only": "true",
    },
    normalize_company_key("Busch Light"): {
        "apollo_search_name": "Anheuser-Busch",
        "domain": "anheuser-busch.com",
        "employer_only": "true",
    },
    normalize_company_key("Stella Artois"): {
        "apollo_search_name": "Anheuser-Busch",
        "domain": "anheuser-busch.com",
        "employer_only": "true",
    },
    normalize_company_key("Blue Moon"): {
        "apollo_search_name": "Molson Coors Beverage Company",
        "domain": "molsoncoors.com",
        "employer_only": "true",
    },
    normalize_company_key("Pacifico"): {
        "apollo_search_name": "Constellation Brands",
        "domain": "cbrands.com",
        "employer_only": "true",
    },
    normalize_company_key("Dos Equis"): {
        "apollo_search_name": "Heineken USA",
        "domain": "heinekenusa.com",
        "employer_only": "true",
    },
    normalize_company_key("Jameson"): {
        "apollo_search_name": "Pernod Ricard",
        "domain": "pernod-ricard.com",
        "employer_only": "true",
    },
    normalize_company_key("Truly"): {
        "apollo_search_name": "The Boston Beer Company",
        "domain": "bostonbeer.com",
        "employer_only": "true",
    },
    normalize_company_key("Samuel Adams"): {
        "apollo_search_name": "The Boston Beer Company",
        "domain": "bostonbeer.com",
        "employer_only": "true",
    },
    normalize_company_key("New Amsterdam"): {
        "apollo_search_name": "E. & J. Gallo Winery",
        "domain": "gallo.com",
        "employer_only": "true",
    },
    normalize_company_key("Snickers"): {
        "apollo_search_name": "Mars",
        "domain": "mars.com",
        "employer_only": "true",
    },
}


def brand_apollo_employer_hint(company_name: str) -> dict[str, str] | None:
    """Where Apollo stores US contacts for this shelf brand, if known."""
    return BRAND_APOLLO_EMPLOYER.get(normalize_company_key(company_name))


def brand_apollo_employer_from_target(target: dict) -> dict[str, str] | None:
    """Target JSON / Cursor employer fields, with code map winning over inferred names."""
    company = (target.get("company_name") or target.get("name") or "").strip()
    mapped = brand_apollo_employer_hint(company)
    if mapped:
        return mapped

    emp = (target.get("apollo_employer_name") or "").strip()
    dom = (target.get("apollo_employer_domain") or "").strip()
    if emp:
        out: dict[str, str] = {"apollo_search_name": emp, "domain": dom}
        raw_only = target.get("apollo_employer_only")
        explicit_only = raw_only is True or str(raw_only).strip().lower() in ("1", "true", "yes")
        # Parent-employer search only when Cursor said so AND names actually differ.
        emp_key = normalize_company_key(emp)
        co_key = normalize_company_key(company)
        names_differ = bool(emp_key and co_key and emp_key != co_key and emp_key not in co_key and co_key not in emp_key)
        if explicit_only and names_differ:
            out["employer_only"] = "true"
        aliases = target.get("apollo_search_aliases")
        if aliases:
            if isinstance(aliases, list):
                out["apollo_search_aliases"] = json.dumps(aliases)
            elif isinstance(aliases, str) and aliases.strip():
                out["apollo_search_aliases"] = aliases.strip()
        return out
    return None


def employer_hint_is_shared(employer_hint: dict[str, str] | None) -> bool:
    return bool(employer_hint and employer_hint.get("apollo_search_name"))


# Not Lia targets — wholesalers / distributors (sell brands to retailers, not shelf sponsors).
DISTRIBUTOR_WHOLESALER_NAME_MARKERS = (
    "distribut",
    "wholesale",
    "wholesaler",
    "sunbelt",
    "charmer",
    "martignetti",
    "southern glazer",
    "republic national",
    "rndc",
    "breakthru",
    "young's market",
    "wine & spirits",
    "wines & spirits",
    "beverage group",  # often distributor holding names
    "fine wine",
    "liberty beverage",
    "johnson brothers",
    "horizon beverage",
    "empire distributors",
    "martin distributing",
    "harbor distributing",
    "golden brands",
    "sgws",
)

DISTRIBUTOR_WHOLESALER_INDUSTRIES = (
    "wholesale",
    "logistics",
    "transportation",
    "warehousing",
)


def is_beverage_distributor_or_wholesaler(org_name: str, industry: str = "") -> bool:
    """True when org is a tier-1/2 distributor — not a consumer shelf brand."""
    n = (org_name or "").strip().lower()
    ind = (industry or "").strip().lower()
    if any(m in n for m in DISTRIBUTOR_WHOLESALER_NAME_MARKERS):
        return True
    if any(m in ind for m in DISTRIBUTOR_WHOLESALER_INDUSTRIES):
        return True
    if "wine" in n and "estate" not in n and any(x in n for x in ("group", "company", "companies", "import")):
        if "distribut" in n or "wholesale" in ind:
            return True
    return False


DEFAULT_BRAND_PROSPECT_BRIEF = (
    "US **shelf brands** (products consumers buy), not corporate parents. "
    "Target the brand's own marketing site and Apollo org (e.g. Fiji Water, Budweiser, Gatorade). "
    "Do NOT output holding companies (AB InBev, Wonderful Company, PepsiCo, Unilever, LVMH). "
    "Optional parent_company field for context only."
)


def is_corporate_holding_target(company_name: str) -> bool:
    """True if this target is a top-level holding / conglomerate, not a consumer brand."""
    key = normalize_company_key(company_name)
    if not key:
        return True
    if key in CORPORATE_HOLDING_KEYS:
        return True
    # Conglomerate-style names without a product brand signal
    holding_phrases = (
        "inbev",
        "holdings inc",
        "holding company",
        "international plc",
        "moet hennessy",
    )
    if any(p in key for p in holding_phrases):
        return True
    return False
