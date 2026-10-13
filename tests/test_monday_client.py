import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from monday_client import DEFAULT_MONDAY_API_VERSION, MondayClient  # noqa: E402


def test_monday_client_default_api_version(monkeypatch) -> None:
    monkeypatch.delenv("MONDAY_API_VERSION", raising=False)
    c = MondayClient("test-key")
    assert DEFAULT_MONDAY_API_VERSION == "2026-07"
    assert c.api_version == "2026-07"
    assert c.headers["API-Version"] == "2026-07"


def test_monday_client_env_api_version(monkeypatch) -> None:
    monkeypatch.setenv("MONDAY_API_VERSION", "2025-10")
    c = MondayClient("test-key")
    assert c.api_version == "2025-10"


def test_monday_client_constructor_override(monkeypatch) -> None:
    monkeypatch.setenv("MONDAY_API_VERSION", "2025-10")
    c = MondayClient("test-key", api_version="2026-01")
    assert c.api_version == "2026-01"
