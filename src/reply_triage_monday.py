"""
Match Gmail reply senders to Monday Master Outreach items and build column updates.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from dotenv import load_dotenv

from monday_client import MondayClient
from prospecting_qa import normalize_email, parse_email_column_value

load_dotenv()

MASTER_BOARD_ID = int(os.getenv("MASTER_BOARD_ID", "18401545002"))
COL_LEAD_STATUS = os.getenv("TRIAGE_COL_LEAD_STATUS", "status")
COL_OUTREACH_STAGE = os.getenv("TRIAGE_COL_OUTREACH_STAGE", "color_mm0x44cb")
COL_INTEREST = os.getenv("TRIAGE_COL_INTEREST", "color_mm0xtvq2")
COL_EMAIL = os.getenv("TRIAGE_COL_EMAIL", "email_mm0xb00t")
COL_NOTES = os.getenv("TRIAGE_COL_NOTES", "text_mm0xz0w2")
COL_LAST_CONTACTED = os.getenv("TRIAGE_COL_LAST_CONTACTED", "date_mm0xerpc")
COL_NEXT_ACTION_DATE = os.getenv("TRIAGE_COL_NEXT_ACTION", "date_mm0x7ga4")
COL_TITLE = os.getenv("TRIAGE_COL_TITLE", "text_mm0xg2xb")

GROUP_ENGAGED = os.getenv("TRIAGE_GROUP_ENGAGED", "group_mm0xj5rd")
GROUP_MEETING = os.getenv("TRIAGE_GROUP_MEETING", "group_mm0xj1qw")
GROUP_DISQUALIFIED = os.getenv("TRIAGE_GROUP_DISQUALIFIED", "group_mm0xtvgg")
GROUP_ACTIVE = os.getenv("TRIAGE_GROUP_ACTIVE", "group_mm0x18c")
GROUP_NEW_LEADS = os.getenv("TRIAGE_GROUP_NEW_LEADS", "group_mm0xbmrj")

def _query_with_retry(monday: MondayClient, query: str, variables: Dict[str, Any], attempts: int = 4) -> Any:
    last: Any = None
    for attempt in range(attempts):
        last = monday.execute_query(query, variables)
        if last is not None:
            return last
        time.sleep(min(2 ** attempt, 8))
    return last


GROUP_BY_HINT = {
    "engaged": GROUP_ENGAGED,
    "meeting": GROUP_MEETING,
    "disqualified": GROUP_DISQUALIFIED,
    "active": GROUP_ACTIVE,
    "new_leads": GROUP_NEW_LEADS,
    "none": "",
}


def column_text(item: Mapping[str, Any], col_id: str) -> str:
    for cv in item.get("column_values") or []:
        if cv.get("id") == col_id:
            return (cv.get("text") or "").strip()
    return ""


def build_email_index(items: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """normalized_email -> list of items (newest id last for stable pick)."""
    index: Dict[str, List[Dict[str, Any]]] = {}
    for it in items:
        for cv in it.get("column_values") or []:
            if cv.get("id") != COL_EMAIL:
                continue
            em = normalize_email(parse_email_column_value(cv))
            if not em:
                break
            index.setdefault(em, []).append(it)
            break
    return index


def pick_best_item(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Prefer Engaged/Meeting/Active over Disqualified when duplicate emails exist."""
    rank = {
        GROUP_MEETING: 100,
        GROUP_ENGAGED: 90,
        GROUP_ACTIVE: 70,
        GROUP_NEW_LEADS: 50,
        GROUP_DISQUALIFIED: 10,
    }

    def score(item: Dict[str, Any]) -> int:
        gid = (item.get("group") or {}).get("id") or ""
        return rank.get(gid, 40)

    return max(candidates, key=score)


def monday_context_for_email(
    index: Dict[str, List[Dict[str, Any]]],
    from_email: str,
) -> Tuple[Optional[Dict[str, Any]], str]:
    items = index.get(normalize_email(from_email)) or []
    if not items:
        return None, "no_monday_match"
    if len(items) == 1:
        return items[0], "single_match"
    return pick_best_item(items), "multi_match_picked_best"


def triage_to_column_values(
    triage: Mapping[str, Any],
    *,
    received_at: str = "",
    reply_type: str = "",
) -> Dict[str, Any]:
    """Map triage JSON to Monday column_values (Notes = short LLM summary only)."""
    cols: Dict[str, Any] = {}
    if triage.get("lead_status"):
        cols[COL_LEAD_STATUS] = {"label": triage["lead_status"]}
    if triage.get("interest_level"):
        cols[COL_INTEREST] = {"label": triage["interest_level"]}
    if received_at:
        cols[COL_LAST_CONTACTED] = {"date": received_at}
    if triage.get("next_action_date"):
        cols[COL_NEXT_ACTION_DATE] = {"date": triage["next_action_date"]}
    note = (triage.get("notes_summary") or "").strip()[:4000]
    if note:
        cols[COL_NOTES] = note
    return cols


def group_id_for_hint(hint: str) -> str:
    return GROUP_BY_HINT.get((hint or "none").strip().lower(), "")


def apply_triage_update(
    monday: MondayClient,
    *,
    board_id: int,
    item_id: str,
    column_values: Dict[str, Any],
    group_id: str,
) -> Tuple[bool, str]:
    if column_values:
        res = monday.update_item_columns(board_id, item_id, column_values)
        if not res or res.get("errors"):
            return False, f"column_update_failed:{res}"
        if not (res.get("data") or {}).get("change_multiple_column_values"):
            return False, f"column_update_empty:{res}"

    if group_id:
        res_g = monday.move_item_to_group(item_id, group_id)
        if not res_g or res_g.get("errors"):
            return False, f"group_move_failed:{res_g}"
        if not (res_g.get("data") or {}).get("move_item_to_group"):
            return False, f"group_move_empty:{res_g}"

    return True, "ok"


def load_board_items(monday: MondayClient, board_id: int) -> List[Dict[str, Any]]:
    """Full board load (slow on ~4k+ rows). Prefer load_triage_index."""
    return monday.get_board_items_with_columns(board_id, limit=500)


def load_triage_index(
    monday: MondayClient,
    board_id: int,
    *,
    page_size: int = 100,
    on_page: Callable[[int, int], None] | None = None,
) -> List[Dict[str, Any]]:
    """
    Paginated fetch with only columns needed for reply matching + Gemini context.
    Much faster than loading every column on the full board.
    """
    col_ids = [
        COL_EMAIL,
        COL_LEAD_STATUS,
        COL_OUTREACH_STAGE,
        COL_TITLE,
    ]
    col_json = json.dumps(col_ids)
    items: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    page_num = 0

    while True:
        page_num += 1
        if cursor:
            query = f"""
            query ($cursor: String!, $limit: Int!) {{
                next_items_page (cursor: $cursor, limit: $limit) {{
                    cursor
                    items {{
                        id
                        name
                        group {{ id title }}
                        column_values (ids: {col_json}) {{ id text value }}
                    }}
                }}
            }}
            """
            variables: Dict[str, Any] = {"cursor": cursor, "limit": page_size}
            data = _query_with_retry(monday, query, variables)
            page = (data or {}).get("data", {}).get("next_items_page") or {}
        else:
            query = f"""
            query ($boardId: ID!, $limit: Int!) {{
                boards (ids: [$boardId]) {{
                    items_page (limit: $limit) {{
                        cursor
                        items {{
                            id
                            name
                            group {{ id title }}
                            column_values (ids: {col_json}) {{ id text value }}
                        }}
                    }}
                }}
            }}
            """
            variables = {"boardId": int(board_id), "limit": page_size}
            data = _query_with_retry(monday, query, variables)
            boards = (data or {}).get("data", {}).get("boards") or []
            page = (boards[0] or {}).get("items_page") or {} if boards else {}

        batch = page.get("items") or []
        if not batch and page.get("cursor") and data is None:
            if on_page:
                on_page(page_num, 0)
            time.sleep(2)
            continue
        items.extend(batch)
        if on_page:
            on_page(page_num, len(batch))

        cursor = page.get("cursor")
        if not cursor:
            break

    return items
