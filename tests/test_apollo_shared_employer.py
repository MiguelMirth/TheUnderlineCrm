import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from apollo_contact_rank import shared_employer_brand_title_ok  # noqa: E402
from apollo_org_resolve import (  # noqa: E402
    _employer_org_is_homonym,
    _merge_people_fl_first,
    _resolve_person_locations,
)
from prospecting_config import APOLLO_FL_PERSON_LOCATIONS, APOLLO_US_PERSON_LOCATIONS  # noqa: E402
from prospecting_qa import title_gate  # noqa: E402


def test_merge_people_fl_first_dedupes() -> None:
    fl = [{"id": "a"}, {"id": "b"}]
    us = [{"id": "b"}, {"id": "c"}]
    merged = _merge_people_fl_first(fl, us)
    assert [p["id"] for p in merged] == ["a", "b", "c"]


def test_shared_employer_us_search_when_fl_required() -> None:
    locs = _resolve_person_locations(
        relax_locations=False,
        person_locations=None,
        require_florida=True,
        shared_employer=True,
    )
    assert locs == APOLLO_US_PERSON_LOCATIONS


def test_direct_brand_fl_search_when_not_shared() -> None:
    locs = _resolve_person_locations(
        relax_locations=False,
        person_locations=None,
        require_florida=True,
        shared_employer=False,
    )
    assert locs == APOLLO_FL_PERSON_LOCATIONS


def test_shared_employer_generic_brand_title() -> None:
    assert shared_employer_brand_title_ok("Brand Marketing Manager", "Absolut")
    assert shared_employer_brand_title_ok("Senior Brand Manager, Patron Tequila", "Patron")
    assert not shared_employer_brand_title_ok("Director of Sales, Southeast", "Absolut")


def test_employer_homonym_photography() -> None:
    hint = {"apollo_search_name": "Heineken USA", "domain": "heinekenusa.com"}
    assert _employer_org_is_homonym(hint, "Joey Heineken Photography")


def test_title_blocks_store_and_sales() -> None:
    ok, r = title_gate("AVP Stores Staffing")
    assert not ok
    ok2, _ = title_gate("VP of Sales")
    assert not ok2
    ok3, _ = title_gate("Director of Brand Experience")
    assert ok3


def test_title_blocks_privacy() -> None:
    ok, r = title_gate("Director of Privacy, Data Security and GRC")
    assert not ok
    assert "privacy" in r or "title_blocked" in r
