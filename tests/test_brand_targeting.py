import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from brand_targeting import (  # noqa: E402
    is_beverage_distributor_or_wholesaler,
    is_corporate_holding_target,
)


def test_holding_companies_blocked() -> None:
    assert is_corporate_holding_target("Anheuser-Busch InBev")
    assert is_corporate_holding_target("The Wonderful Company")
    assert is_corporate_holding_target("PepsiCo")


def test_distributors_blocked() -> None:
    assert is_beverage_distributor_or_wholesaler("The Charmer Sunbelt Group")
    assert is_beverage_distributor_or_wholesaler("Martignetti Companies")
    assert not is_beverage_distributor_or_wholesaler("Lay's")


def test_shelf_brands_allowed() -> None:
    assert not is_corporate_holding_target("Fiji Water")
    assert not is_corporate_holding_target("Budweiser")
    assert not is_corporate_holding_target("Gatorade")
    assert not is_corporate_holding_target("Monster Energy")
