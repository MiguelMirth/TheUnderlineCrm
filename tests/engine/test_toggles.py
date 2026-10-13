"""Toggle labels (relaxed / tightened), payload validation, and cap overrides."""
from __future__ import annotations

import pytest

from engine.models import ToggleSpec, resolve_caps, resolve_toggle_values
from engine.presets import PRESETS


def _bool(default: bool, relaxed_when: str | None) -> ToggleSpec:
    return ToggleSpec(id="t", label="t", kind="bool", default=default, relaxed_when=relaxed_when)


def _int(default: int, relaxed_when: str | None) -> ToggleSpec:
    return ToggleSpec(id="t", label="t", kind="int", default=default, relaxed_when=relaxed_when)


def test_bool_filter_turning_off_is_relaxed():
    spec = _bool(True, relaxed_when="off")
    assert spec.status_for(True) == "default"
    assert spec.status_for(False) == "relaxed"


def test_bool_that_tightens_when_off_is_tightened():
    spec = _bool(True, relaxed_when="on")  # allow_global_org: turning it off is tighter
    assert spec.status_for(False) == "tightened"


def test_bool_switch_with_no_label_is_changed_not_relaxed():
    spec = _bool(False, relaxed_when=None)  # discover_new_events
    assert spec.status_for(True) == "changed"


def test_int_threshold_lower_loosens():
    spec = _int(80, relaxed_when="lower")
    assert spec.status_for(70) == "relaxed"
    assert spec.status_for(90) == "tightened"


def test_int_cap_higher_loosens():
    spec = _int(3, relaxed_when="higher")
    assert spec.status_for(4) == "relaxed"
    assert spec.status_for(2) == "tightened"


def test_zero_default_cap_means_any_positive_value_is_tighter():
    spec = _int(0, relaxed_when="lower")  # venue max_per_company, 0 = unlimited
    assert spec.status_for(2) == "tightened"


def test_choice_relaxed_value_is_named():
    spec = ToggleSpec(id="t", label="t", kind="choice", default="a", choices=["a", "b"], relaxed_when="b")
    assert spec.status_for("b") == "relaxed"


def test_resolve_fills_defaults_and_accepts_overrides():
    venue = PRESETS["underline"].vertical("venue_rental")
    values = resolve_toggle_values(venue, {"us_fallback": True})
    assert values["us_fallback"] is True
    assert values["florida_person_only"] is True
    assert values["max_per_company"] == 0


def test_resolve_refuses_unknown_toggle():
    venue = PRESETS["underline"].vertical("venue_rental")
    with pytest.raises(ValueError, match="unknown toggle"):
        resolve_toggle_values(venue, {"not_a_toggle": True})


def test_resolve_refuses_wrong_types():
    venue = PRESETS["underline"].vertical("venue_rental")
    with pytest.raises(ValueError, match="true or false"):
        resolve_toggle_values(venue, {"us_fallback": 1})
    with pytest.raises(ValueError, match="whole number"):
        resolve_toggle_values(venue, {"max_per_company": True})


def test_resolve_caps_refuses_unknown_and_negative():
    concert = PRESETS["underline"].vertical("concert_series")
    assert resolve_caps(concert, {"target": 100}).target == 100
    with pytest.raises(ValueError, match="unknown cap"):
        resolve_caps(concert, {"nonsense": 1})
    with pytest.raises(ValueError, match="non-negative"):
        resolve_caps(concert, {"target": -5})
