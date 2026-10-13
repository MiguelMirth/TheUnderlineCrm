import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from active_outreach_cleanup import classify_active_outreach_row  # noqa: E402


def test_missing_email_and_bad_title() -> None:
    row = {
        "company_name": "Health Resources and Services Administration (HRSA)",
        "email": "ali@hrsa.gov",
        "title": "Program Officer",
        "first_name": "Ann",
        "last_name": "Lee",
    }
    verdict, reasons = classify_active_outreach_row(row, company_blocklist=set())
    assert verdict == "delete"
    assert any("blocked_email" in r or "bad_org" in r for r in reasons)


def test_good_sponsorship_contact_kept() -> None:
    row = {
        "company_name": "Fever-Tree",
        "email": "jane@fever-tree.com",
        "title": "Director of Brand Partnerships",
        "first_name": "Jane",
        "last_name": "Doe",
    }
    verdict, reasons = classify_active_outreach_row(row, company_blocklist=set())
    assert verdict == "keep"
    assert not reasons


def test_company_pulse_no_contact() -> None:
    row = {
        "company_name": "Alani Nu",
        "email": "",
        "title": "",
        "first_name": "",
        "last_name": "",
    }
    verdict, reasons = classify_active_outreach_row(row, company_blocklist=set())
    assert verdict == "delete"
    assert "company_pulse_no_contact" in reasons
    assert "missing_email" in reasons
