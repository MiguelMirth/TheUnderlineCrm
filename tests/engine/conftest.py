"""Shared fixtures for engine tests. Every test gets its own database and no spend ceilings from .env."""
from __future__ import annotations

import pytest

from engine.spend import CEILING_ENV


@pytest.fixture(autouse=True)
def _no_ceilings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in CEILING_ENV.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("RUN_MAX_TAVILY_QUERIES", raising=False)
    # A developer key in the shell must not make startup call Monday or arm a live push.
    monkeypatch.delenv("MONDAY_API_KEY", raising=False)
    monkeypatch.delenv("APOLLO_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("ENGINE_LIVE_PUSH_ENABLED", raising=False)


@pytest.fixture
def store(tmp_path):
    from engine.store import Store

    return Store(str(tmp_path / "engine.db"))
