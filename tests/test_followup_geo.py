import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from send_followups_sequence import in_florida  # noqa: E402


def test_blank_state_stays():
    assert in_florida("") is True
    assert in_florida("   ") is True


def test_florida_values():
    assert in_florida("FL") is True
    assert in_florida("Florida") is True
    assert in_florida("Miami-Dade") is True


def test_other_states_drop():
    assert in_florida("Iowa") is False
    assert in_florida("California") is False
    assert in_florida("WA") is False
