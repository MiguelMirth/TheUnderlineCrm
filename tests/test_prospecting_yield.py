"""Yield-path fixes: shared_employer false positives, title scoring, bank industry allow."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from apollo_contact_rank import (  # noqa: E402
    shared_employer_brand_title_ok,
    should_enrich_person,
    sponsorship_title_score,
)
from brand_targeting import brand_apollo_employer_from_target  # noqa: E402
from prospecting_qa import org_industry_sponsor_allowed, sponsor_org_viable  # noqa: E402


def test_cmo_title_scores_above_floor() -> None:
    assert sponsorship_title_score("CMO") >= 45
    assert sponsorship_title_score("Chief Marketing Officer") >= 45
    assert sponsorship_title_score("Global Marketing Director") >= 45


def test_shared_employer_allows_marketing_director() -> None:
    assert shared_employer_brand_title_ok("Global Marketing Director", "Claire's")
    assert shared_employer_brand_title_ok("Director of Marketing", "Lilly Pulitzer")


def test_employer_hint_not_shared_when_same_brand() -> None:
    hint = brand_apollo_employer_from_target(
        {
            "company_name": "Claire's",
            "apollo_employer_name": "Claire's",
            "apollo_employer_domain": "claires.com",
            "apollo_employer_only": False,
        }
    )
    assert hint is not None
    assert "employer_only" not in hint


def test_employer_hint_shared_only_for_true_parent() -> None:
    hint = brand_apollo_employer_from_target(
        {
            "company_name": "First National Bank of South Miami",
            "apollo_employer_name": "United Community Banks, Inc.",
            "apollo_employer_domain": "ucbi.com",
            "apollo_employer_only": True,
        }
    )
    assert hint is not None
    assert hint.get("employer_only") == "true"


def test_banking_industry_allowed_for_underline() -> None:
    assert org_industry_sponsor_allowed("financial services")
    assert org_industry_sponsor_allowed("banking")
    ok, reason = sponsor_org_viable(
        org_name="Santander Bank",
        org_industry="financial services",
        brand_mode=True,
        shared_employer=False,
    )
    assert ok, reason


def test_claires_marketing_director_passes_pre_enrich() -> None:
    ok, reason, pts = should_enrich_person(
        {"title": "Global Marketing Director", "country": "United States"},
        shelf_brand="Claire's",
        shared_employer=False,
        research_mode=True,
    )
    assert ok is True, reason
    assert pts >= 45
