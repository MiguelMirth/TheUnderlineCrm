import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from email_outreach import make_email3_body, make_email4_body  # noqa: E402
from prospect_scoring import build_prospect_rationale, score_prospect  # noqa: E402
from prospecting_qa import person_geo_tier  # noqa: E402


def test_person_geo_tier_miami() -> None:
    tier, label = person_geo_tier({"city": "Miami", "state": "Florida", "country": "United States"})
    assert tier == 3
    assert label == "south_florida_metro"


def test_score_prospect_high_for_miami_brand_marketer() -> None:
    person = {"city": "Miami", "state": "Florida", "country": "United States", "seniority": "director"}
    org = {"name": "Fiji Water", "industry": "Food & Beverages", "country": "United States"}
    score, _ = score_prospect(
        person=person,
        org=org,
        title="Director of Brand Partnerships",
        shelf_brand="Fiji Water",
        category="Lifestyle + Premium Beverage + Entertainment",
    )
    assert score >= 60


def test_build_prospect_rationale() -> None:
    text = build_prospect_rationale(
        person={"city": "Miami", "state": "FL"},
        org={"name": "Red Bull"},
        title="Brand Manager",
        shelf_brand="Red Bull",
        category="Retail CPG + QSR",
        geo_score=3,
        fit_score=72,
    )
    assert "Miami" in text
    assert "72/100" in text


def test_email3_body_mentions_lululemon() -> None:
    text, _ = make_email3_body("Alex", "Acme")
    assert "Lululemon" in text
    assert "Alex" in text


def test_email4_is_new_thread_copy() -> None:
    text, _ = make_email4_body("Alex", "Acme")
    assert "timing isn't right" in text
