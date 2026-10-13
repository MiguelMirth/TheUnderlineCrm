"""Tests for concert_series_qa — title gate, email dedupe, protected accounts."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from concert_series_config import (  # noqa: E402
    CONCERT_SERIES_ORG_KEYWORD_TAGS,
    CONCERT_SERIES_PERSON_TITLES,
    concert_employee_ranges,
)
from concert_series_qa import (  # noqa: E402
    concert_blacklist_blocked,
    concert_email_ok,
    concert_nonprofit_name_blocked,
    concert_org_viable,
    concert_protected_account_blocked,
    concert_title_gate,
)
from prospecting_qa import (  # noqa: E402
    item_is_protected,
    is_personal_email_domain,
    normalize_company_key,
    org_industry_blocked,
)


def test_sponsorship_titles_pass() -> None:
    assert concert_title_gate("Director of Sponsorships")[0]
    assert concert_title_gate("VP Brand Partnerships")[0]
    assert concert_title_gate("Head of Experiential Marketing")[0]
    assert concert_title_gate("CMO")[0]
    assert concert_title_gate("Entertainment Marketing Manager")[0]


def test_collab_titles_fail_without_paid_context() -> None:
    for title in (
        "Community Relations Manager",
        "Partnerships Manager",
        "Director of Communications",
        "Events Manager",
        "Hospitality Manager",
    ):
        ok, reason = concert_title_gate(title)
        assert not ok, title
        assert reason == "title_collab_not_paid"


def test_intern_and_finance_blocked() -> None:
    ok, reason = concert_title_gate("Sponsorship Intern")
    assert not ok
    assert "intern" in reason
    ok2, _ = concert_title_gate("Director of Finance")
    assert not ok2


def test_irrelevant_and_empty_blocked() -> None:
    assert not concert_title_gate("Software Engineer")[0]
    ok, reason = concert_title_gate("")
    assert not ok
    assert reason == "empty_title"
    assert not concert_title_gate("Wedding Planner")[0]


def test_email_dedupe_only() -> None:
    monday = {"alice@example.com", "bob@acme.com"}
    ok, reason = concert_email_ok("alice@example.com", monday)
    assert not ok
    assert "already on Monday" in reason
    assert concert_email_ok("new.person@brand.com", monday)[0]


def test_gov_email_blocked() -> None:
    ok, reason = concert_email_ok("cmo@miami.gov", set())
    assert not ok
    assert "email QA" in reason or "email_domain" in reason


def test_protected_company_and_domain() -> None:
    names = {normalize_company_key("Jackson Health")}
    domains = {"jacksonhealth.org"}
    reason = concert_protected_account_blocked(
        org_name="Jackson Health System",
        website="https://www.jacksonhealth.org",
        email="new.person@other.com",
        protected_names=names,
        protected_domains=domains,
    )
    assert reason
    assert "protected" in reason

    reason2 = concert_protected_account_blocked(
        org_name="Some Other Brand",
        website="https://otherbrand.com",
        email="cmo@jacksonhealth.org",
        protected_names=names,
        protected_domains=domains,
    )
    assert reason2
    assert "jacksonhealth.org" in reason2


def test_personal_email_domain_not_treated_as_company_domain() -> None:
    assert is_personal_email_domain("gmail.com")
    reason = concert_protected_account_blocked(
        org_name="Fresh Brand Co",
        website="https://freshbrand.com",
        email="cmo@gmail.com",
        protected_names=set(),
        protected_domains={"gmail.com"},  # should be ignored on the email side
    )
    # website is not protected; gmail should not block via email domain match
    # (is_personal_email_domain skips the email-domain check)
    assert reason is None


def test_unprotected_company_allowed() -> None:
    reason = concert_protected_account_blocked(
        org_name="New Beverage Co",
        website="https://newbev.com",
        email="partnerships@newbev.com",
        protected_names={normalize_company_key("Jackson Health")},
        protected_domains={"jacksonhealth.org"},
    )
    assert reason is None


def test_item_is_protected_by_group_or_status() -> None:
    assert item_is_protected(group_id="group_mm0xj5rd", status="Uncontacted")
    assert item_is_protected(group_id="group_mm0x18c", status="Replied")
    assert item_is_protected(group_id="group_mm0xj1qw", status="")
    assert item_is_protected(group_id="group_mm0xnfca", status="In Sequence")
    assert item_is_protected(group_id="group_mm0x18c", status="Proposal Sent")
    assert not item_is_protected(group_id="group_mm0xbmrj", status="Uncontacted")
    assert not item_is_protected(group_id="group_mm0x18c", status="In Sequence")


def test_blacklist_blocks_known_partners() -> None:
    forbidden = {"airbnb", "chewy"}
    assert concert_blacklist_blocked("Airbnb", forbidden)
    assert concert_blacklist_blocked("Chewy Inc", forbidden) is not None
    assert concert_blacklist_blocked("Unknown Soda Co", forbidden) is None


def test_agency_and_civic_orgs_blocked() -> None:
    ok, reason = concert_org_viable(
        org_name="North Star Marketing Agency",
        org_industry="marketing & advertising",
        annual_revenue=50_000_000,
        estimated_employees=200,
    )
    assert not ok
    assert "industry_block" in reason or "non_sponsor" in reason

    assert org_industry_blocked("civic & social organization")
    assert concert_nonprofit_name_blocked("Miami Parks Foundation")
    assert concert_nonprofit_name_blocked("Friends of the Riverwalk")
    assert concert_nonprofit_name_blocked("South Florida Chamber of Commerce")

    ok_civic, reason_civic = concert_org_viable(
        org_name="Civic Alliance of Miami",
        org_industry="civic & social organization",
        annual_revenue=80_000_000,
        estimated_employees=120,
    )
    assert not ok_civic


def test_cpg_brand_passes_org_viable() -> None:
    ok, reason = concert_org_viable(
        org_name="Acme Snacks",
        org_industry="consumer packaged goods",
        email="cmo@acmesnacks.com",
        annual_revenue=50_000_000,
        estimated_employees=200,
    )
    assert ok, reason


def test_paid_search_titles_drop_collab_desks() -> None:
    lowered = [t.lower() for t in CONCERT_SERIES_PERSON_TITLES]
    for banned in (
        "community relations",
        "corporate social responsibility",
        "events",
        "hospitality",
        "partnership",
        "partnerships",
        "director of partnerships",
    ):
        assert banned not in lowered
    assert "brand partnerships" in lowered
    assert "director of sponsorships" in lowered


def test_org_keywords_drop_restaurants_and_entertainment() -> None:
    tags = {t.lower() for t in CONCERT_SERIES_ORG_KEYWORD_TAGS}
    assert "restaurants" not in tags
    assert "entertainment" not in tags
    assert "insurance" in tags
    assert "alcoholic beverages" in tags


def test_employee_ranges_start_at_51() -> None:
    ranges = concert_employee_ranges(51)
    assert "1,10" not in ranges
    assert "11,20" not in ranges
    assert "21,50" not in ranges
    assert ranges[0] == "51,100"
    assert "10001+" in ranges
