"""Preset schema and the Underline preset: valid, complete, and consistent with the gate registry."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from engine.gates import CHAINS
from engine.models import Caps, CrmContract, Preset, SourceSpec, ToggleSpec, VerticalSpec
from engine.presets import PRESETS, validate_preset


def test_underline_preset_is_valid():
    preset = PRESETS["underline"]
    assert validate_preset(preset) == []
    assert [v.id for v in preset.verticals] == [
        "sponsor_brands",
        "concert_series",
        "venue_rental",
    ]


def test_every_gate_chain_is_registered():
    for vertical in PRESETS["underline"].verticals:
        assert vertical.gate_chain in CHAINS


def test_crm_contract_matches_prospect_push_columns():
    crm = PRESETS["underline"].crm
    # Column ids are the live New Leads contract. A drift here is a board write bug.
    assert crm.columns["email"] == "email_mm0xb00t"
    assert crm.columns["vertical"] == "dropdown_mm0xx10b"
    assert crm.columns["status"] == "status"
    assert crm.new_leads_group_default == "group_mm0xbmrj"
    assert set(crm.protected_group_ids) == {"group_mm0xj5rd", "group_mm0xj1qw", "group_mm0xnfca"}


def test_research_verticals_use_cursor_and_apollo_verticals_use_gemini():
    by_id = {v.id: v for v in PRESETS["underline"].verticals}
    assert by_id["sponsor_brands"].llm_qa == "cursor_score"
    assert by_id["concert_series"].llm_qa == "gemini"
    assert by_id["venue_rental"].llm_qa == "gemini"


def test_venue_defaults_to_florida_person_and_no_us_fallback():
    venue = PRESETS["underline"].vertical("venue_rental")
    values = {t.id: t.default for t in venue.toggles}
    assert values["florida_person_only"] is True
    assert values["us_fallback"] is False


def test_bool_toggle_default_must_be_bool():
    with pytest.raises(ValidationError):
        ToggleSpec(id="x", label="x", kind="bool", default=1)


def test_int_toggle_rejects_bool_default():
    with pytest.raises(ValidationError):
        ToggleSpec(id="x", label="x", kind="int", default=True)


def test_relaxed_when_must_match_kind():
    with pytest.raises(ValidationError):
        ToggleSpec(id="x", label="x", kind="bool", default=True, relaxed_when="lower")
    with pytest.raises(ValidationError):
        ToggleSpec(id="x", label="x", kind="int", default=1, relaxed_when="on")


def test_choice_default_must_be_a_listed_choice():
    with pytest.raises(ValidationError):
        ToggleSpec(id="x", label="x", kind="choice", default="z", choices=["a", "b"])


def test_duplicate_toggle_ids_rejected():
    toggle = ToggleSpec(id="same", label="x", kind="bool", default=True)
    with pytest.raises(ValidationError):
        VerticalSpec(
            id="v",
            label="v",
            icp="",
            monday_vertical="v",
            source=SourceSpec(kind="csv"),
            gate_chain="csv",
            toggles=[toggle, toggle],
            caps=Caps(),
        )


def test_validate_preset_flags_wrong_qa_for_source():
    preset = PRESETS["underline"]
    bad = preset.vertical("concert_series").model_copy(update={"llm_qa": "cursor_score"})
    broken = preset.model_copy(update={"verticals": [bad]})
    problems = validate_preset(broken)
    assert any("Apollo people sources use gemini" in p for p in problems)


def test_validate_preset_flags_unknown_gate_chain():
    preset = PRESETS["underline"]
    bad = preset.vertical("venue_rental").model_copy(update={"gate_chain": "nope"})
    broken = preset.model_copy(update={"verticals": [bad]})
    assert any("unknown gate_chain" in p for p in validate_preset(broken))


def test_preset_refuses_duplicate_vertical_ids():
    preset = PRESETS["underline"]
    v = preset.vertical("venue_rental")
    with pytest.raises(ValidationError):
        Preset(
            id="p",
            name="p",
            place="p",
            year=2026,
            crm=preset.crm,
            blacklist_path="x",
            verticals=[v, v],
        )


def test_crm_contract_round_trips_through_json():
    crm = PRESETS["underline"].crm
    assert CrmContract.model_validate_json(crm.model_dump_json()) == crm
