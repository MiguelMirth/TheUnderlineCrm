import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from apollo_contact_rank import (  # noqa: E402
    prefer_us_candidates,
    rank_contacts_for_sponsorship,
    sponsorship_title_score,
)
from sponsor_research import _domain_from_evidence_url, _to_prospect_target  # noqa: E402


def test_prefer_us_candidates_drops_tagged_non_us() -> None:
    people = [
        {"id": "1", "country": "United Kingdom"},
        {"id": "2", "country": "United States"},
        {"id": "3"},
    ]
    filtered = prefer_us_candidates(people, require_us=True)
    assert [p["id"] for p in filtered] == ["2", "3"]


def test_sponsorship_title_score_prefers_sponsorship_roles() -> None:
    assert sponsorship_title_score("Director of Sponsorship") >= sponsorship_title_score(
        "Marketing Coordinator"
    )
    assert sponsorship_title_score("VP Brand Partnerships") > sponsorship_title_score(
        "Sales Manager"
    )


def test_rank_contacts_title_before_geo() -> None:
    people = [
        {"id": "1", "title": "Sales Director", "state": "Florida", "has_email": True},
        {
            "id": "2",
            "title": "Director of Sponsorship",
            "state": "Texas",
            "has_email": True,
        },
    ]
    ranked = rank_contacts_for_sponsorship(people, shelf_brand="Maker's Mark")
    assert ranked[0]["id"] == "2"


def test_domain_from_evidence_url() -> None:
    assert _domain_from_evidence_url("https://www.makersmark.com/about") == "makersmark.com"
    assert _domain_from_evidence_url("") == ""
    assert _domain_from_evidence_url("https://school.edu/page") == ""


def test_to_prospect_target_infers_brand_domain_only() -> None:
    row = {
        "company_name": "Chase",
        "evidence_url": "https://www.chase.com/community",
        "confidence": 85,
    }
    assert _to_prospect_target(row)["domain"] == "chase.com"

    event_row = {
        "company_name": "Maker's Mark",
        "evidence_url": "https://paraisomiamibeach.com/partners",
        "confidence": 85,
    }
    assert _to_prospect_target(event_row)["domain"] == "makersmark.com"
