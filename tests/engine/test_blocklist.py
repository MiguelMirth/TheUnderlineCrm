"""Blocklist rules: exact email, corporate domain (personal exception), full name, probable name, company, protected, blacklist.txt."""
from __future__ import annotations

from engine.crm import Blocklist, build_blocklist, read_blacklist


def _row(name="", email="", first="", last="", website="", status="", group="group_mm0xbmrj"):
    return {
        "name": name,
        "email": email,
        "first": first,
        "last": last,
        "website": website,
        "status": status,
        "group": group,
    }


def _bl(rows, blacklist=frozenset()) -> Blocklist:
    return build_blocklist({"rows": rows}, set(blacklist))


def test_exact_email_on_the_board_blocks_that_address_only():
    bl = _bl([_row("Acme", email="jane@acme.com")])
    assert bl.email_hit("Jane@Acme.com ") is not None
    assert bl.email_hit("john@acme.com") is None


def test_corporate_domain_on_the_board_blocks_new_contacts_at_that_domain():
    bl = _bl([_row("Acme", email="jane@acme.com")])
    assert bl.domain_hit("acme.com") is not None
    assert bl.domain_hit("www.acme.com") is not None
    assert bl.domain_hit("other.com") is None


def test_personal_inbox_domains_never_block_even_when_the_board_uses_them():
    bl = _bl([_row("Solo", email="founder@gmail.com", website="https://gmail.com")])
    assert "gmail.com" not in bl.corp_domains
    assert bl.domain_hit("gmail.com") is None
    # The exact address still blocks, because that is the email rule, not the domain rule.
    assert bl.email_hit("founder@gmail.com") is not None
    assert bl.email_hit("someone.else@gmail.com") is None


def test_website_host_on_the_board_is_a_corporate_domain():
    bl = _bl([_row("Acme", website="https://www.acme.com/about")])
    assert bl.domain_hit("acme.com") is not None


def test_full_name_exact_match_blocks_after_enrich():
    bl = _bl([_row("Acme", first="Jane", last="Doe")])
    assert bl.name_hit("jane", "DOE") is not None
    assert bl.name_hit("Jane", "Smith") is None
    assert bl.name_hit("Jane", "Do***") is None  # an obfuscated last name is not an exact name


def test_probable_name_blocks_same_first_name_same_company_with_matching_prefix():
    bl = _bl([_row("Acme Foods", first="Jane", last="Doe")])
    assert bl.probable_name_hit("Jane", "Do***", "Acme Foods Inc") is not None
    assert bl.probable_name_hit("Jane", "Sm***", "Acme Foods") is None
    assert bl.probable_name_hit("Janet", "Do***", "Acme Foods") is None
    assert bl.probable_name_hit("Jane", "Do***", "Other Co") is None


def test_probable_name_needs_an_obfuscated_last_name():
    bl = _bl([_row("Acme Foods", first="Jane", last="Doe")])
    assert bl.probable_name_hit("Jane", "Doe", "Acme Foods") is None


def test_company_on_the_board_blocks_by_name_and_legal_suffix():
    bl = _bl([_row("Acme Foods")])
    assert bl.company_hit("Acme Foods Inc.") is not None
    assert bl.company_hit("Acme Foods") is not None
    assert bl.company_hit("Acme Beverages") is None


def test_short_board_names_match_exactly_only():
    bl = _bl([_row("Inter")])
    assert bl.company_hit("International Paper") is None
    assert bl.company_hit("inter") is not None


def test_blacklist_company_blocks_like_a_board_row():
    bl = _bl([], blacklist={"miami-dade county"})
    assert bl.company_hit("Miami-Dade County") is not None


def test_protected_accounts_by_group_or_status():
    bl = _bl(
        [
            _row("Replied Co", email="x@replied.com", group="group_mm0xj5rd"),
            _row("Status Co", status="Meeting Set"),
            _row("Quiet Co", status="Uncontacted"),
        ]
    )
    assert bl.protected_hit("Replied Co") is not None
    assert bl.protected_hit("Status Co") is not None
    assert bl.protected_hit("Quiet Co") is None
    assert bl.protected_hit("Unknown Brand", "replied.com") is not None


def test_read_blacklist_skips_comments_and_blanks_and_never_writes(tmp_path):
    path = tmp_path / "blacklist.txt"
    original = "# comment\n\nMiami-Dade County\n  Chewy  \n"
    path.write_text(original, encoding="utf-8")
    before = path.stat().st_mtime_ns
    names = read_blacklist(path)
    assert names == {"miami-dade county", "chewy"}
    assert path.read_text(encoding="utf-8") == original
    assert path.stat().st_mtime_ns == before


def test_read_blacklist_missing_file_is_empty(tmp_path):
    assert read_blacklist(tmp_path / "nope.txt") == set()


def test_empty_company_never_blocks():
    bl = _bl([_row("Acme")])
    assert bl.company_hit("") is None
    assert bl.company_hit("   ") is None
