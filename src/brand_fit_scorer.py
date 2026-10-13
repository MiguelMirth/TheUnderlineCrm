"""
Score sponsor candidates for Underline fit — Cursor (cloud REST or SDK), heuristic fallback.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import List, Tuple

from cursor_cloud_client import cursor_cloud_prompt
from cursor_model import research_model_label, sdk_model_selection
from prospecting_config import MONDAY_VERTICAL_LABELS
from sponsor_name_qa import is_plausible_brand_name

_SCORE_JSON_RE = re.compile(r"\[[\s\S]*\]", re.MULTILINE)

# Heuristic is intentionally conservative — never auto-passes PROSPECT_MIN_CONFIDENCE (80).
_HEURISTIC_CONFIDENCE_CAP = 65

_MIAMI_MARKERS = ("miami", "south florida", "florida", "brickell", "wynwood")
_SPONSOR_MARKERS = ("sponsor", "partner", "official", "presenting", "activation")
_CONSUMER_MARKERS = (
    "water",
    "beverage",
    "beer",
    "spirit",
    "wine",
    "energy",
    "fitness",
    "wellness",
    "fashion",
    "bank",
    "health",
    "tech",
    "cpg",
    "food",
    "retail",
)


def _scoring_backend() -> str:
    """
    auto  — cloud REST on Windows; SDK then cloud elsewhere
    cloud — Cursor Cloud Agents REST API (recommended on Windows)
    sdk   — local cursor-sdk bridge (macOS/Linux)
    """
    return os.getenv("CURSOR_SCORING_BACKEND", "auto").strip().lower()


def _heuristic_score(candidate: dict) -> dict:
    """Fallback scoring without LLM — capped below auto-push threshold."""
    name = (candidate.get("company_name") or "").strip()
    if not is_plausible_brand_name(name):
        return {
            **candidate,
            "alignment_score": 0,
            "miami_activity_score": 0,
            "confidence": 0,
            "vertical": "Lifestyle + Premium Beverage + Entertainment",
            "category": "Lifestyle + Premium Beverage + Entertainment",
            "alignment_reason": "Rejected: not a plausible brand name",
            "reject": True,
        }

    evidence = (candidate.get("sponsorship_evidence") or "").lower()
    url = (candidate.get("evidence_url") or "").lower()
    blob = f"{name.lower()} {evidence} {url}"

    miami = 55 if any(m in blob for m in _MIAMI_MARKERS) else 30
    alignment = 35
    if any(m in blob for m in _CONSUMER_MARKERS):
        alignment += 15
    if any(m in blob for m in _SPONSOR_MARKERS):
        alignment += 10
    if candidate.get("event_source"):
        alignment += 5

    confidence = int((miami * 0.35) + (alignment * 0.65))
    confidence = max(0, min(_HEURISTIC_CONFIDENCE_CAP, confidence))

    vertical = "Lifestyle + Premium Beverage + Entertainment"
    if any(x in blob for x in ("fitness", "energy", "sport", "gatorade")):
        vertical = "Fitness + Performance Beverages"
    elif any(x in blob for x in ("bank", "finance", "health", "hospital", "tech", "software")):
        if "health" in blob or "hospital" in blob:
            vertical = "Healthcare + Wellness"
        elif "bank" in blob or "finance" in blob:
            vertical = "Finance + Banking"
        elif "tech" in blob or "software" in blob:
            vertical = "Technology"
    elif any(x in blob for x in ("retail", "grocery", "qsr", "restaurant", "snack")):
        vertical = "Retail CPG + QSR"

    return {
        **candidate,
        "alignment_score": alignment,
        "miami_activity_score": miami,
        "confidence": confidence,
        "vertical": vertical,
        "category": vertical,
        "alignment_reason": f"Heuristic only ({confidence}/100): needs LLM scoring for push",
        "recommended_angle": "concert series / park activation",
        "rationale": f"Event sponsor research ({candidate.get('event_source', '')})",
    }


def _parse_cursor_json(text: str) -> List[dict]:
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.I)
    text = re.sub(r"\s*```$", "", text).strip()
    m = _SCORE_JSON_RE.search(text)
    if not m:
        raise ValueError("no JSON array in Cursor response")
    parsed = json.loads(m.group(0))
    if not isinstance(parsed, list):
        raise ValueError("expected JSON array")
    return parsed


def _build_scoring_prompt(candidates: list[dict], context: str) -> str:
    slim = [
        {
            "company_name": c.get("company_name"),
            "event_source": c.get("event_source"),
            "sponsorship_evidence": (c.get("sponsorship_evidence") or "")[:300],
            "evidence_url": c.get("evidence_url"),
        }
        for c in candidates
    ]
    labels = ", ".join(f'"{x}"' for x in MONDAY_VERTICAL_LABELS)
    return f"""You score sponsor prospects for The Underline (Miami park + Levitt concert series).

CONTEXT:
{context}

CANDIDATES (from Miami event sponsor research):
{json.dumps(slim, ensure_ascii=False)}

Return ONLY a JSON array with one object per candidate (same company_name). Schema:
{{
  "company_name": "...",
  "alignment_score": 0-100,
  "miami_activity_score": 0-100,
  "confidence": 0-100,
  "vertical": one of [{labels}],
  "alignment_reason": "one sentence",
  "recommended_angle": "playground|concert|wellness|dining|community",
  "sponsorship_evidence": "one sentence with why they sponsor events",
  "reject": false
}}

Rules:
- confidence >= 80 only if: real consumer brand, Miami/event sponsorship evidence, budget to sponsor activations.
- Set reject=true for junk (page titles, generic words like Fashion/Partner/Platform, media partners, hotels, government).
- Prefer diverse sectors (not all beer).
- Keep sponsorship_evidence factual from the input; do not invent URLs.
"""


def _merge_cursor_scores(candidates: list[dict], text: str) -> List[dict]:
    scored_rows = _parse_cursor_json(text)
    by_name = {str(r.get("company_name", "")).strip().lower(): r for r in scored_rows}

    out: list[dict] = []
    missing: list[str] = []
    rejected: list[str] = []
    for c in candidates:
        name = (c.get("company_name") or "").strip()
        row = by_name.get(name.lower())
        if not row:
            missing.append(name)
            continue
        if row.get("reject"):
            rejected.append(name)
            continue
        merged = {**c, **{k: v for k, v in row.items() if v is not None}}
        merged["confidence"] = int(merged.get("confidence") or 0)
        merged["category"] = merged.get("vertical") or merged.get("category") or "Retail CPG + QSR"
        if not merged.get("sponsorship_evidence"):
            merged["sponsorship_evidence"] = c.get("sponsorship_evidence") or row.get("alignment_reason") or ""
        out.append(merged)

    if missing:
        sample = ", ".join(missing[:4])
        extra = f" +{len(missing) - 4} more" if len(missing) > 4 else ""
        print(f"    Cursor omitted {len(missing)} brand(s) from response: {sample}{extra}")
    if rejected:
        print(f"    Cursor rejected {len(rejected)} brand(s) as junk")
    return out


def _score_batch_size() -> int:
    return max(3, int(os.getenv("CURSOR_SCORE_BATCH_SIZE", "6")))


def _score_with_cursor_cloud(candidates: list[dict], context: str) -> List[dict]:
    batch_size = _score_batch_size()
    all_scored: list[dict] = []
    total_batches = (len(candidates) + batch_size - 1) // batch_size
    for i in range(0, len(candidates), batch_size):
        chunk = candidates[i : i + batch_size]
        batch_num = i // batch_size + 1
        if total_batches > 1:
            print(f"    Batch {batch_num}/{total_batches} ({len(chunk)} brands)...")
        prompt = _build_scoring_prompt(chunk, context)
        text = cursor_cloud_prompt(prompt, name=f"underline-scoring-{batch_num}")
        all_scored.extend(_merge_cursor_scores(chunk, text))
    return all_scored


def _score_with_cursor_sdk(candidates: list[dict], context: str) -> List[dict]:
    from cursor_sdk_compat import apply_windows_shims

    apply_windows_shims()
    from cursor_sdk import Agent, AgentOptions, LocalAgentOptions

    api_key = os.getenv("CURSOR_API_KEY", "").strip()
    if not api_key:
        raise ValueError("CURSOR_API_KEY not set")

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    batch_size = _score_batch_size()
    all_scored: list[dict] = []
    total_batches = (len(candidates) + batch_size - 1) // batch_size
    for i in range(0, len(candidates), batch_size):
        chunk = candidates[i : i + batch_size]
        batch_num = i // batch_size + 1
        if total_batches > 1:
            print(f"    Batch {batch_num}/{total_batches} ({len(chunk)} brands)...")
        prompt = _build_scoring_prompt(chunk, context)
        result = Agent.prompt(
            prompt,
            AgentOptions(
                api_key=api_key,
                model=sdk_model_selection(),
                local=LocalAgentOptions(cwd=root, setting_sources=[]),
            ),
        )
        if result.status != "finished":
            raise RuntimeError(f"Cursor agent status={result.status}")
        text = (result.result or "").strip()
        if not text:
            raise ValueError("empty Cursor result")
        all_scored.extend(_merge_cursor_scores(chunk, text))
    return all_scored


def score_with_cursor(candidates: list[dict], context: str) -> Tuple[List[dict], str]:
    """Score via Cursor — cloud REST (Windows-safe) or local SDK."""
    backend = _scoring_backend()
    if backend == "cloud" or (backend == "auto" and sys.platform == "win32"):
        return _score_with_cursor_cloud(candidates, context), "cursor_cloud"

    if backend in ("sdk", "auto"):
        try:
            return _score_with_cursor_sdk(candidates, context), "cursor_sdk"
        except Exception:
            if backend == "sdk":
                raise
            return _score_with_cursor_cloud(candidates, context), "cursor_cloud"

    return _score_with_cursor_cloud(candidates, context), "cursor_cloud"


def score_research_candidates(
    candidates: list[dict],
    *,
    context: str,
    max_candidates: int = 30,
) -> Tuple[List[dict], str]:
    """Score candidates; returns (scored_list, method)."""
    plausible = [c for c in candidates if is_plausible_brand_name(c.get("company_name") or "")]
    batch = plausible[:max_candidates]
    use_cursor = os.getenv("PROSPECT_USE_CURSOR_SCORING", "true").lower() == "true"

    if use_cursor and os.getenv("CURSOR_API_KEY", "").strip():
        model = research_model_label()
        backend = _scoring_backend()
        label = "Cloud API" if backend == "cloud" or (backend == "auto" and sys.platform == "win32") else "SDK"
        try:
            batches = (len(batch) + _score_batch_size() - 1) // _score_batch_size()
            batch_note = f", {batches} batch(es)" if batches > 1 else ""
            print(f"  Scoring {len(batch)} brands with Cursor {label} ({model}{batch_note})...")
            scored, method = score_with_cursor(batch, context)
            scored.sort(key=lambda x: int(x.get("confidence") or 0), reverse=True)
            return scored, method
        except Exception as e:
            print(f"  Cursor scoring failed ({e}); using heuristic fallback.")

    scored = [_heuristic_score(c) for c in batch]
    scored = [s for s in scored if not s.get("reject")]
    scored.sort(key=lambda x: int(x.get("confidence") or 0), reverse=True)
    return scored, "heuristic"
