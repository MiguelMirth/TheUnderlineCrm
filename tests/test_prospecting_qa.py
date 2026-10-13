import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from prospecting_qa import (
    company_collides_with_crm,
    email_blocked,
    geo_person_org_gate,
    normalize_company_key,
    normalize_email,
    org_industry_blocked,
    org_name_blocked,
    parse_annual_revenue_usd,
    person_in_florida,
    sponsor_org_viable,
    title_gate,
)


def test_normalize_email():
    assert normalize_email("  Foo@Bar.COM ") == "foo@bar.com"


def test_geo_florida_ok():
    person = {"city": "Miami", "state": "Florida", "country": "United States"}
    org = {"city": "New York", "state": "New York", "country": "United States"}
    ok, _ = geo_person_org_gate(person, org, require_us=True, require_florida=True)
    assert ok


def test_geo_non_us_fail():
    person = {"city": "London", "state": "England", "country": "United Kingdom"}
    org = {"city": "London", "state": "England", "country": "United Kingdom"}
    ok, reason = geo_person_org_gate(person, org, require_us=True, require_florida=False)
    assert not ok
    assert "not_us" in reason or "person_country" in reason


def test_geo_canada_person_rejected():
    person = {"city": "Toronto", "state": "Ontario", "country": "Canada"}
    org = {"city": "Miami", "state": "Florida", "country": "United States"}
    ok, reason = geo_person_org_gate(person, org, require_us=True, require_florida=False)
    assert not ok


def test_title_blocks_intern():
    ok, r = title_gate("Marketing Intern")
    assert not ok
    assert "intern" in r


def test_org_name_blocks_fc():
    assert org_name_blocked("Manchester United FC") is not None


def test_west_hollywood_california_is_not_florida() -> None:
    assert person_in_florida({"city": "West Hollywood", "state": "California"}) is False
    assert person_in_florida({"city": "Hollywood", "state": "Florida"}) is True


def test_geo_person_only_florida_rejects_ny_person() -> None:
    person = {"city": "New York", "state": "New York", "country": "United States"}
    org = {"city": "Miami", "state": "Florida", "country": "United States"}
    ok, reason = geo_person_org_gate(
        person, org, require_us=True, require_florida=True, person_florida_only=True
    )
    assert not ok
    assert "person_not_florida" in reason


def test_geo_global_org_allowed_with_fl_person() -> None:
    person = {"city": "Miami", "state": "Florida", "country": "United States"}
    org = {"city": "Salzburg", "state": "", "country": "Austria"}
    ok, _ = geo_person_org_gate(
        person, org, require_us=True, require_florida=True,
        person_florida_only=True, allow_global_org=True,
    )
    assert ok


def test_geo_china_person_us_org_rejected():
    person = {"city": "Shanghai", "state": "", "country": "China"}
    org = {"city": "Redmond", "state": "Washington", "country": "United States"}
    ok, reason = geo_person_org_gate(person, org, require_us=True, require_florida=False)
    assert not ok
    assert "person_country_not_us" in reason


def test_title_blocks_ceo():
    ok, r = title_gate("Chief Executive Officer")
    assert not ok
    assert "ceo" in r or "chief executive" in r


def test_title_allows_vp_brand_partnerships():
    ok, _ = title_gate("Vice President, Brand Partnerships")
    assert ok


def test_title_blocks_chairman():
    ok, r = title_gate("Chairman of the Board")
    assert not ok


def test_email_blocks_gov() -> None:
    assert email_blocked("iali@hrsa.gov") is not None
    assert email_blocked("user@nih.gov") is not None
    assert email_blocked("amaisonet@guess.com") is None


def test_org_blocks_samhsa() -> None:
    assert org_name_blocked("Substance Abuse and Mental Health Services Administration (SAMHSA)") is not None


def test_org_blocks_generic_clinic() -> None:
    assert org_name_blocked("Mental Health Clinics") is not None


def test_org_allows_baptist_health() -> None:
    assert org_name_blocked("Baptist Health South Florida") is None


def test_org_allows_jackson_health() -> None:
    assert org_name_blocked("Jackson Health System") is None


def test_university_blocked() -> None:
    assert org_name_blocked("University of Texas") is not None


def test_boston_childrens_hospital_blocked() -> None:
    from prospecting_qa import out_of_market_hospital_blocked

    assert out_of_market_hospital_blocked("Boston Children's Hospital", "Massachusetts", "Boston") is not None


def test_email_blocks_edu() -> None:
    assert email_blocked("student@culinary.edu") is not None


def test_org_industry_blocks_market_research() -> None:
    assert org_industry_blocked("Market Research") is not None
    assert org_industry_blocked("Marketing & Advertising") is not None


def test_sponsor_blocks_numerator(monkeypatch) -> None:
    monkeypatch.setenv("PROSPECT_SPONSOR_STRICT", "true")
    ok, reason = sponsor_org_viable(
        org_name="Numerator",
        org_industry="Market Research",
        email="vp@numerator.com",
    )
    assert not ok
    assert "non_sponsor" in reason or "industry" in reason


def test_sponsor_blocks_epsilon_agency(monkeypatch) -> None:
    monkeypatch.setenv("PROSPECT_SPONSOR_STRICT", "true")
    ok, reason = sponsor_org_viable(
        org_name="Epsilon",
        org_industry="Marketing & Advertising",
        email="danny@epsilon.com",
    )
    assert not ok


def test_sponsor_allows_consumer_brands(monkeypatch) -> None:
    monkeypatch.setenv("PROSPECT_SPONSOR_STRICT", "true")
    for name, industry in (
        ("The Wonderful Company", "Food Production"),
        ("The Walt Disney Company", "Entertainment"),
        ("The Wonderful Company", "Food Production"),
        ("Dr. Squatch", "Health, Wellness and Fitness"),
    ):
        ok, reason = sponsor_org_viable(
            org_name=name,
            org_industry=industry,
            email="brand@example.com",
        )
        assert ok, f"{name}: {reason}"


def test_parse_annual_revenue() -> None:
    assert parse_annual_revenue_usd("50M") == 50_000_000
    assert parse_annual_revenue_usd(250000000) == 250_000_000


def test_sponsor_shared_employer_skips_revenue(monkeypatch) -> None:
    monkeypatch.setenv("PROSPECT_SPONSOR_STRICT", "true")
    monkeypatch.setenv("PROSPECT_BRAND_MODE", "true")
    from prospecting_qa import sponsor_org_viable

    ok, _ = sponsor_org_viable(
        org_name="PepsiCo",
        org_industry="Food & Beverages",
        annual_revenue=5_000_000,
        brand_mode=True,
        shared_employer=True,
    )
    assert ok


def test_sponsor_rejects_low_revenue_known(monkeypatch) -> None:
    monkeypatch.setenv("PROSPECT_SPONSOR_STRICT", "true")
    monkeypatch.setenv("PROSPECT_MIN_ORG_REVENUE", "100000000")
    ok, reason = sponsor_org_viable(
        org_name="Small CPG Co",
        org_industry="Food Production",
        email="x@smallcpg.com",
        annual_revenue=25_000_000,
    )
    assert not ok
    assert "revenue_below_min" in reason


def test_company_collides_exact_and_substring() -> None:
    crm_lower = {"publix super markets", "baptist health south florida"}
    crm_norms = {normalize_company_key(x) for x in crm_lower}
    assert company_collides_with_crm("Publix Super Markets", crm_lower, crm_norms)
    assert company_collides_with_crm("publix", crm_lower, crm_norms)
    assert company_collides_with_crm("Baptist Health South Florida", crm_lower, crm_norms)
    assert not company_collides_with_crm("Whole Foods Market", crm_lower, crm_norms)


def test_company_collides_normalized() -> None:
    crm_lower = {"acme corp"}
    crm_norms = {normalize_company_key("acme corp")}
    assert company_collides_with_crm("ACME Corp.", crm_lower, crm_norms)


def test_company_does_not_over_block_partial_substring() -> None:
    crm_lower = {"tyson"}
    crm_norms = {normalize_company_key("tyson")}
    assert not company_collides_with_crm("Tyson Foods, Inc.", crm_lower, crm_norms)
