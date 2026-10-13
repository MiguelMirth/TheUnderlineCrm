"""
Underline context for sponsor fit scoring (deck, partners, programming).
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Iterable, List, Tuple

_ROOT = Path(__file__).resolve().parent.parent

# Primary deck locations (repo `data/` folder)
BRAND_DECK_CANDIDATES: Tuple[Path, ...] = (
    _ROOT / "data" / "Brand Deck_Underline.pdf",
    _ROOT / "data" / "inputs" / "Brand Deck_Underline.pdf",
)

LEVITT_DECK_CANDIDATES: Tuple[Path, ...] = (
    _ROOT / "data" / "Levitt Music Series Deck.pdf",
    _ROOT / "data" / "inputs" / "Levitt Music Series Deck.pdf",
)


def _read_pdf_text(path: Path, max_pages: int = 12) -> str:
    if not path.is_file():
        return ""
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(str(path))
        chunks: list[str] = []
        for page in reader.pages[:max_pages]:
            text = page.extract_text() or ""
            if text.strip():
                chunks.append(text.strip())
        return "\n\n".join(chunks)
    except Exception:
        return ""


def _resolve_deck_path(candidates: Iterable[Path], env_var: str) -> Path | None:
    override = (os.getenv(env_var) or "").strip()
    if override:
        p = Path(override)
        if not p.is_absolute():
            p = _ROOT / p
        if p.is_file():
            return p
    for c in candidates:
        if c.is_file():
            return c
    return None


def load_deck_excerpts(
    *,
    max_pages_per_deck: int = 10,
    max_chars_per_deck: int = 4500,
) -> List[Tuple[str, str]]:
    """
    Load text from both Underline decks when present.
    Returns list of (label, excerpt) — brand deck first, then Levitt music series.
    """
    out: list[tuple[str, str]] = []

    brand_path = _resolve_deck_path(BRAND_DECK_CANDIDATES, "UNDERLINE_BRAND_DECK_PATH")
    if brand_path:
        text = _read_pdf_text(brand_path, max_pages=max_pages_per_deck)
        if text:
            out.append(("Brand Deck (park, amenities, sponsorship packages)", text[:max_chars_per_deck]))

    levitt_path = _resolve_deck_path(LEVITT_DECK_CANDIDATES, "UNDERLINE_LEVITT_DECK_PATH")
    if levitt_path:
        text = _read_pdf_text(levitt_path, max_pages=max_pages_per_deck)
        if text:
            out.append(("Levitt Music Series Deck (concerts, activations)", text[:max_chars_per_deck]))

    return out


@lru_cache(maxsize=1)
def load_partners_data() -> dict:
    path = _ROOT / "data" / "inputs" / "underline_known_partners.json"
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_miami_events_seed(path: str | None = None) -> list[dict]:
    p = Path(path) if path else _ROOT / "data" / "inputs" / "miami_events_seed.json"
    if not p.is_file():
        return []
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def build_underline_context_block() -> str:
    """Compact context for LLM fit scoring (both decks + partners JSON)."""
    partners = load_partners_data()
    pillars = partners.get("programming_pillars") or []
    past = partners.get("past_partners_mentioned") or []
    verticals = partners.get("good_fit_verticals") or []
    avoid = partners.get("avoid") or []

    lines = [
        "THE UNDERLINE (Miami): 10-mile linear park under Metrorail; concerts (Levitt series), "
        "wellness, dining, playgrounds, community activations. Sponsors want on-site presence, not logo-only.",
        "",
        "Programming pillars:",
        *[f"- {x}" for x in pillars],
        "",
        "Past / reference partners:",
        ", ".join(past[:20]),
        "",
        "Good-fit sectors:",
        ", ".join(verticals),
        "",
        "Avoid:",
        *[f"- {x}" for x in avoid],
    ]

    decks = load_deck_excerpts()
    if decks:
        lines.append("")
        lines.append("Sponsorship decks (excerpts):")
        for label, excerpt in decks:
            lines.append(f"\n--- {label} ---\n{excerpt}")
    else:
        lines.append("")
        lines.append(
            "(Deck PDFs not found — expected "
            "data/Brand Deck_Underline.pdf and data/Levitt Music Series Deck.pdf)"
        )

    return "\n".join(lines)


def rotate_events(events: list[dict], count: int, *, offset: int | None = None) -> list[dict]:
    """Round-robin pick events for this run."""
    if not events or count <= 0:
        return []
    if offset is None:
        offset = int(os.getenv("RESEARCH_EVENT_OFFSET", "0") or "0")
    n = len(events)
    out: list[dict] = []
    for i in range(count):
        out.append(events[(offset + i) % n])
    return out
