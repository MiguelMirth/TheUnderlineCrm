"""Cursor model selection helpers (composer fast vs standard)."""
from __future__ import annotations

import os
from typing import Any


def composer_use_fast() -> bool:
    return os.getenv("CURSOR_COMPOSER_FAST", "false").strip().lower() == "true"


class FastModelBlocked(RuntimeError):
    """The engine refuses Cursor fast models. They are a different, cheaper pass."""


def research_model_id() -> str:
    return os.getenv("CURSOR_RESEARCH_MODEL", "composer-2.5").strip()


def assert_standard_model() -> str:
    """
    Raise unless the configured Cursor model is a standard (non-fast) id.

    composer-2.5 is the latest Composer (Cursor models API, October 2026). Its default
    variant is fast=true, so every engine call must also force fast off. A Grok id is
    allowed. An id that contains "fast", or CURSOR_COMPOSER_FAST=true, is not.
    """
    if composer_use_fast():
        raise FastModelBlocked("CURSOR_COMPOSER_FAST is on. The engine only calls standard models.")
    model_id = research_model_id()
    if "fast" in model_id.lower():
        raise FastModelBlocked(f"Cursor model {model_id!r} is a fast model. The engine will not call it.")
    return model_id


def research_model_label() -> str:
    mid = research_model_id()
    if mid.startswith("composer") and not composer_use_fast():
        return f"{mid} (standard)"
    if mid.startswith("composer") and composer_use_fast():
        return f"{mid} (fast)"
    return mid


def cloud_model_payload() -> dict[str, Any]:
    """Model object for POST /v1/agents — disables fast by default (cheaper standard)."""
    model_id = research_model_id()
    payload: dict[str, Any] = {"id": model_id}
    if model_id.startswith("composer"):
        payload["params"] = [{"id": "fast", "value": "true" if composer_use_fast() else "false"}]
    return payload


def sdk_model_selection():
    """ModelSelection for cursor-sdk AgentOptions."""
    from cursor_sdk import ModelParameterValue, ModelSelection

    model_id = research_model_id()
    params = ()
    if model_id.startswith("composer"):
        params = (ModelParameterValue(id="fast", value="true" if composer_use_fast() else "false"),)
    return ModelSelection(id=model_id, params=params)
