import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from apollo_brand_domains import guess_brand_domains  # noqa: E402
from apollo_org_resolve import (  # noqa: E402
    _brand_org_token_fit,
    _score_org_candidate,
    person_org_acceptable,
)


def test_guess_brand_domains() -> None:
    assert "makersmark.com" in guess_brand_domains("Maker's Mark")
    assert "miniusa.com" in guess_brand_domains("MINI USA")
    assert "neutrogena.com" in guess_brand_domains("Neutrogena")
    assert "bacardi.com" in guess_brand_domains("BACARDÍ")


def test_token_fit_rejects_makers_market() -> None:
    assert _brand_org_token_fit("Maker's Mark", "Makers Market") < 0.65
    assert _brand_org_token_fit("Maker's Mark", "Maker's Mark Distillery") >= 0.65


def test_token_fit_rejects_mini_melts() -> None:
    assert _brand_org_token_fit("MINI USA", "Mini Melts USA") < 0.65
    assert _brand_org_token_fit("MINI USA", "MINI USA") >= 0.65


def test_person_org_rejects_mini_melts_homonym() -> None:
    hint = {
        "apollo_search_name": "BMW of North America",
        "domain": "bmwusa.com",
        "employer_only": "true",
        "apollo_search_aliases": '["BMW Group US", "BMW Group"]',
    }
    assert not person_org_acceptable("MINI USA", "Mini Melts USA", hint)
    assert person_org_acceptable(
        "MINI USA",
        "BMW Group US",
        hint,
    )


def test_score_trusts_official_domain_over_bad_industry() -> None:
    org = {
        "name": "Neutrogena",
        "primary_domain": "neutrogena.com",
        "country": "United States",
        "industry": "mechanical or industrial engineering",
    }
    score = _score_org_candidate("Neutrogena", org, domain="neutrogena.com", shelf_brand="Neutrogena")
    assert score >= 70.0
