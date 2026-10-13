"""Preset registry. A second client is a new module here, registered below."""
from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from engine.gates import CHAINS
from engine.models import Preset, PresetSettings
from engine.presets.config import apply_settings
from engine.presets.underline import UNDERLINE_PRESET

log = logging.getLogger("engine.presets")

PRESETS: dict[str, Preset] = {UNDERLINE_PRESET.id: UNDERLINE_PRESET}


def validate_preset(preset: Preset) -> list[str]:
    """Problems that would make a run unsafe or unrunnable. Empty list = valid."""
    problems: list[str] = []
    for vertical in preset.verticals:
        if vertical.gate_chain not in CHAINS:
            problems.append(f"{vertical.id}: unknown gate_chain {vertical.gate_chain!r}")
        if vertical.source.kind == "research_events" and vertical.llm_qa != "cursor_score":
            problems.append(f"{vertical.id}: research sources use cursor_score QA")
        if vertical.source.kind == "apollo_people" and vertical.llm_qa != "gemini":
            problems.append(f"{vertical.id}: Apollo people sources use gemini QA")
    return problems


def get_preset(preset_id: str, store: Any | None = None) -> Preset:
    """Factory preset, with the Preset screen's saved document applied when a store is passed."""
    if preset_id not in PRESETS:
        raise KeyError(preset_id)
    base = PRESETS[preset_id]
    if store is None:
        return base
    raw = store.get_preset_settings(preset_id)
    if not raw:
        return base
    try:
        return apply_settings(base, PresetSettings.model_validate(raw))
    except (ValidationError, ValueError):
        log.exception("saved preset %s could not be applied; using the factory preset", preset_id)
        return base
