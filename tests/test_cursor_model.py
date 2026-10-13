import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import pytest

from cursor_model import (  # noqa: E402
    FastModelBlocked,
    assert_standard_model,
    cloud_model_payload,
    research_model_label,
)


def test_cloud_model_standard_by_default(monkeypatch) -> None:
    monkeypatch.delenv("CURSOR_COMPOSER_FAST", raising=False)
    monkeypatch.setenv("CURSOR_RESEARCH_MODEL", "composer-2.5")
    payload = cloud_model_payload()
    assert payload["id"] == "composer-2.5"
    assert payload["params"] == [{"id": "fast", "value": "false"}]
    assert research_model_label() == "composer-2.5 (standard)"


def test_assert_standard_model_rejects_fast(monkeypatch) -> None:
    monkeypatch.delenv("CURSOR_COMPOSER_FAST", raising=False)
    monkeypatch.setenv("CURSOR_RESEARCH_MODEL", "composer-2.5")
    assert assert_standard_model() == "composer-2.5"
    monkeypatch.setenv("CURSOR_COMPOSER_FAST", "true")
    with pytest.raises(FastModelBlocked):
        assert_standard_model()
    monkeypatch.setenv("CURSOR_COMPOSER_FAST", "false")
    monkeypatch.setenv("CURSOR_RESEARCH_MODEL", "composer-2.5-fast")
    with pytest.raises(FastModelBlocked):
        assert_standard_model()


def test_cloud_model_fast_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("CURSOR_COMPOSER_FAST", "true")
    monkeypatch.setenv("CURSOR_RESEARCH_MODEL", "composer-2.5")
    payload = cloud_model_payload()
    assert payload["params"] == [{"id": "fast", "value": "true"}]
    assert research_model_label() == "composer-2.5 (fast)"
