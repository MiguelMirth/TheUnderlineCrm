import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from apollo_client import ApolloClient  # noqa: E402
from apollo_org_resolve import (  # noqa: E402
    _org_name_suspicious,
    _score_org_candidate,
    organization_name_variants,
    organization_names_match,
)
from prospecting_config import DEFAULT_PERSON_SENIORITIES  # noqa: E402


def test_variants_strip_legal_suffix() -> None:
    v = organization_name_variants("Tyson Foods, Inc.")
    assert "Tyson Foods" in v
    assert "Tyson Foods, Inc." in v


def test_match_tyson_and_monster() -> None:
    assert organization_names_match("Tyson Foods, Inc.", "Tyson Foods")
    assert organization_names_match("Monster Beverage Corporation", "Monster Beverage")
    assert not organization_names_match("Tyson Foods", "Monster Beverage")


def test_match_coca_cola() -> None:
    assert organization_names_match("The Coca-Cola Company", "Coca-Cola")


def test_suspicious_org_names() -> None:
    assert _org_name_suspicious("Oreo", "DESIGN OREO")
    assert _org_name_suspicious("Corona", "Organizacion Corona")
    assert _org_name_suspicious("Lacoste", "Perrier & Lacoste, LLC")
    assert _org_name_suspicious("Lacoste", "Lucy Lacoste Gallery")


def test_score_penalizes_wrong_budweiser_co() -> None:
    bad = {
        "name": "Budweiser Co",
        "primary_domain": "budweiser.com",
        "country": "United States",
        "industry": "information technology & services",
    }
    good = {
        "name": "Anheuser-Busch",
        "primary_domain": "anheuser-busch.com",
        "country": "United States",
        "industry": "food & beverages",
    }
    assert _score_org_candidate("Budweiser", bad, domain="budweiser.com") < _score_org_candidate(
        "Budweiser", good, domain="anheuser-busch.com"
    )


def test_default_person_seniorities_skip_c_suite() -> None:
    assert DEFAULT_PERSON_SENIORITIES
    assert "director" in DEFAULT_PERSON_SENIORITIES
    assert "c_suite" not in DEFAULT_PERSON_SENIORITIES


def test_orgs_from_search_response() -> None:
    data = {"organizations": [{"id": "abc"}]}
    assert ApolloClient.orgs_from_search_response(data)[0]["id"] == "abc"
    data2 = {"accounts": [{"organization_id": "xyz"}]}
    assert ApolloClient.orgs_from_search_response(data2)[0]["organization_id"] == "xyz"

