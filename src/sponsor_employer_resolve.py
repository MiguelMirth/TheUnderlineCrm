"""
Infer US Apollo employer (parent company) for shelf brands — generic, not per-brand hardcoding.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from apollo_brand_domains import guess_brand_domains, shelf_domain_trusted
from brand_targeting import brand_apollo_employer_hint
from cursor_cloud_client import cursor_cloud_prompt

_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]", re.MULTILINE)


def _cursor_employer_resolve_enabled() -> bool:
    explicit = os.getenv("PROSPECT_CURSOR_EMPLOYER_RESOLVE", "").strip().lower()
    if explicit in ("0", "false", "no"):
        return False
    if explicit in ("1", "true", "yes"):
        return True
    research = os.getenv("PROSPECT_RESEARCH_MODE", "false").lower() in ("1", "true", "yes")
    return research and bool(os.getenv("CURSOR_API_KEY", "").strip())


def _canonical_shelf_domain(company_name: str, existing: str = "") -> str:
    """Accent-safe brand domain; reject event-site hosts."""
    guessed = guess_brand_domains(company_name)
    if existing and shelf_domain_trusted(company_name, existing):
        return existing.strip().lower().removeprefix("www.")
    return guessed[0] if guessed else ""


def enrich_targets_for_apollo(targets: list[dict], *, force_cursor: bool = False) -> list[dict]:
    """Attach guessed domains and optional Cursor-inferred employer fields to each target."""
    need_cursor: list[dict] = []
    out: list[dict] = []

    for row in targets:
        t = dict(row)
        name = (t.get("company_name") or t.get("name") or "").strip()
        t["domain"] = _canonical_shelf_domain(name, (t.get("domain") or "").strip())
        if brand_apollo_employer_hint(name) or (t.get("apollo_employer_name") or "").strip():
            out.append(t)
            continue
        need_cursor.append(t)
        out.append(t)

    use_cursor = force_cursor or _cursor_employer_resolve_enabled()
    if need_cursor and use_cursor and os.getenv("CURSOR_API_KEY", "").strip():
        try:
            inferred = _cursor_infer_employers(need_cursor)
            by_name = {
                (r.get("company_name") or "").strip().lower(): r
                for r in inferred
                if (r.get("company_name") or "").strip()
            }
            for i, t in enumerate(out):
                key = (t.get("company_name") or t.get("name") or "").strip().lower()
                extra = by_name.get(key)
                if not extra:
                    continue
                if not (t.get("apollo_employer_name") or "").strip():
                    t["apollo_employer_name"] = (extra.get("apollo_employer_name") or "").strip()
                if not (t.get("apollo_employer_domain") or "").strip():
                    t["apollo_employer_domain"] = (extra.get("apollo_employer_domain") or "").strip()
                if extra.get("employer_only") is not None:
                    t["apollo_employer_only"] = extra.get("employer_only")
                aliases = extra.get("apollo_search_aliases")
                if aliases and not t.get("apollo_search_aliases"):
                    t["apollo_search_aliases"] = aliases
                out[i] = t
        except Exception as e:
            print(f"  Employer inference skipped (Cursor): {e}")

    return out


def _cursor_infer_employers(targets: list[dict]) -> list[dict]:
    lines = []
    for t in targets:
        name = (t.get("company_name") or t.get("name") or "").strip()
        cat = (t.get("category") or "").strip()
        ev = (t.get("sponsorship_evidence") or "")[:120]
        lines.append(f"- {name} | {cat} | {ev}")

    prompt = f"""You help map US consumer **shelf brands** to the company that employs brand marketing / sponsorship staff (for B2B prospecting in Apollo).

For each brand below, return the US **legal employer** Apollo would list (not a distributor, not a homonym).
If marketers sit at a parent (e.g. Gatorade → PepsiCo), use the parent. If the brand is its own US company, use the brand.

Return ONLY a JSON array (no markdown). Each object:
- "company_name" (exact string from input)
- "apollo_employer_name" (US employer name for Apollo org search)
- "apollo_employer_domain" (primary corporate domain, no https — required)
- "apollo_search_aliases" (array of 1-3 alternate employer names as Apollo lists them, e.g. ["BMW Group US", "BMW Group"])
- "employer_only" (boolean: true when employer differs from shelf brand name)

Brands:
{chr(10).join(lines)}
"""
    raw = cursor_cloud_prompt(
        prompt,
        name="underline-employer-resolve",
        timeout_s=int(os.getenv("CURSOR_EMPLOYER_TIMEOUT", "120")),
    )
    m = _JSON_ARRAY_RE.search(raw)
    if not m:
        return []
    data = json.loads(m.group(0))
    return [x for x in data if isinstance(x, dict)]
