"""
CRM snapshot and blocklist.

- The Monday board is read once into a snapshot (email, first and last name, website, status, group).
  The snapshot has a TTL (CRM_SNAPSHOT_TTL_HOURS). It refreshes at Start when stale or on the Refresh
  button, never mid-run. The engine never writes to Monday from this module.
- data/inputs/blacklist.txt is the single human-edited company list. The engine reads it and never
  writes it.
- Company and corporate-domain collisions with any board row block a new contact (plan overrule 6).
  Personal inbox domains never block (PERSONAL_EMAIL_DOMAINS).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from prospecting_qa import (
    PROTECTED_GROUP_IDS,
    PROTECTED_STATUS_LABELS,
    company_collides_with_crm,
    email_domain_key,
    is_personal_email_domain,
    normalize_company_key,
    normalize_email,
    parse_email_column_value,
    website_domain_key,
)

if TYPE_CHECKING:
    from engine.models import CrmContract, Preset
    from engine.store import Store

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TTL_HOURS = 12.0


class CrmUnavailable(RuntimeError):
    """The snapshot is missing or stale and cannot be refreshed (for example, no Monday key)."""


# ---------------------------------------------------------------------------
# Config readers (env read at call time, never cached at import)
# ---------------------------------------------------------------------------


def monday_api_key() -> str:
    return os.getenv("MONDAY_API_KEY", "").strip()


def snapshot_ttl_hours() -> float:
    raw = os.getenv("CRM_SNAPSHOT_TTL_HOURS", "").strip()
    try:
        return float(raw) if raw else DEFAULT_TTL_HOURS
    except ValueError:
        return DEFAULT_TTL_HOURS


def board_id(contract: "CrmContract") -> str:
    override = (contract.board_id_override or "").strip()
    if override:
        return override
    return (os.getenv(contract.board_id_env, "").strip() or contract.board_id_default).strip()


def new_leads_group_id(contract: "CrmContract") -> str:
    override = (contract.new_leads_group_override or "").strip()
    if override:
        return override
    return (os.getenv(contract.new_leads_group_env, "").strip() or contract.new_leads_group_default).strip()


def blacklist_path(preset: "Preset") -> Path:
    return ROOT / preset.blacklist_path


def read_blacklist(path: Path) -> set[str]:
    """Lowercase company names from blacklist.txt. Read-only: this function never writes the file."""
    if not path.is_file():
        return set()
    names: set[str] = set()
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if s and not s.startswith("#"):
                names.add(s.lower())
    return names


# ---------------------------------------------------------------------------
# Snapshot age
# ---------------------------------------------------------------------------


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def snapshot_age_hours(fetched_at: str, now: Optional[datetime] = None) -> float:
    current = now or datetime.now(timezone.utc)
    return max(0.0, (current - _parse_iso(fetched_at)).total_seconds() / 3600.0)


def is_stale(fetched_at: str, ttl_hours: float, now: Optional[datetime] = None) -> bool:
    return snapshot_age_hours(fetched_at, now) >= ttl_hours


# ---------------------------------------------------------------------------
# Monday read
# ---------------------------------------------------------------------------


def fetch_crm_snapshot(monday: Any, board: str, contract: "CrmContract") -> dict[str, Any]:
    """
    One paged pass over the board. Read-only GraphQL. Returns rows with the fields the blocklist needs.
    Raises CrmUnavailable if Monday returns nothing (a failed read must never look like an empty board).
    """
    import json as _json

    cols = contract.columns
    col_ids = [cols["email"], cols["first_name"], cols["last_name"], cols["website"], cols["status"]]
    col_json = _json.dumps(col_ids)
    rows: list[dict[str, Any]] = []
    cursor: Optional[str] = None
    page_size = 200

    while True:
        if cursor:
            query = f"""
            query ($cursor: String!, $limit: Int!) {{
                next_items_page (cursor: $cursor, limit: $limit) {{
                    cursor
                    items {{ id name group {{ id }} column_values (ids: {col_json}) {{ id text value }} }}
                }}
            }}
            """
            data = monday.execute_query(query, {"cursor": cursor, "limit": page_size})
            page = ((data or {}).get("data") or {}).get("next_items_page") or {}
        else:
            query = f"""
            query ($boardId: ID!, $limit: Int!) {{
                boards (ids: [$boardId]) {{
                    items_page (limit: $limit) {{
                        cursor
                        items {{ id name group {{ id }} column_values (ids: {col_json}) {{ id text value }} }}
                    }}
                }}
            }}
            """
            data = monday.execute_query(query, {"boardId": int(board), "limit": page_size})
            if data is None:
                raise CrmUnavailable("Monday read failed. The board snapshot was not refreshed.")
            boards = ((data or {}).get("data") or {}).get("boards") or []
            if not boards:
                raise CrmUnavailable(f"Monday board {board} was not returned. Check MASTER_BOARD_ID and the API key.")
            page = (boards[0] or {}).get("items_page") or {}

        for item in page.get("items") or []:
            rows.append(_row_from_item(item, cols))

        cursor = page.get("cursor")
        if not cursor:
            break

    return {
        "board_id": board,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows": rows,
    }


def _row_from_item(item: dict[str, Any], cols: dict[str, str]) -> dict[str, Any]:
    values: dict[str, Any] = {"name": (item.get("name") or "").strip(), "group": ((item.get("group") or {}).get("id") or "")}
    values.update({"email": "", "website": "", "status": "", "first": "", "last": ""})
    for cv in item.get("column_values") or []:
        cid = cv.get("id")
        if cid == cols["email"]:
            values["email"] = normalize_email(parse_email_column_value(cv))
        elif cid == cols["website"]:
            values["website"] = (cv.get("text") or "").strip()
        elif cid == cols["status"]:
            values["status"] = (cv.get("text") or "").strip()
        elif cid == cols["first_name"]:
            values["first"] = (cv.get("text") or "").strip()
        elif cid == cols["last_name"]:
            values["last"] = (cv.get("text") or "").strip()
    return values


# ---------------------------------------------------------------------------
# Blocklist
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Blocklist:
    emails: frozenset[str] = frozenset()
    corp_domains: frozenset[str] = frozenset()
    company_names: frozenset[str] = frozenset()  # lowercase raw names from the board and blacklist.txt
    company_keys: frozenset[str] = frozenset()  # normalize_company_key of the same names
    full_names: frozenset[str] = frozenset()  # "first last" lowercase, for exact name blocks after enrich
    people_by_company: dict[str, frozenset[tuple[str, str]]] = field(default_factory=dict)
    protected_companies: frozenset[str] = frozenset()
    protected_domains: frozenset[str] = frozenset()
    board_rows: int = 0

    def email_hit(self, email: str) -> Optional[str]:
        e = normalize_email(email)
        if e and e in self.emails:
            return f"{e} is already on the board"
        return None

    def domain_hit(self, *domains: str) -> Optional[str]:
        """Corporate domains only. Personal inbox domains (gmail.com and similar) never block."""
        for raw in domains:
            d = website_domain_key(raw or "")
            if not d or "." not in d or is_personal_email_domain(d):
                continue
            if d in self.corp_domains:
                return f"{d} is on the board"
        return None

    def company_hit(self, company: str) -> Optional[str]:
        name = (company or "").strip()
        if not name:
            return None
        if company_collides_with_crm(name, self.company_names, self.company_keys):
            return f"{normalize_company_key(name) or name.lower()} is on the board or in blacklist.txt"
        return None

    def protected_hit(self, company: str, *domains: str) -> Optional[str]:
        key = normalize_company_key(company)
        if key and key in self.protected_companies:
            return f"{key} is in an active conversation or closed deal"
        for raw in domains:
            d = website_domain_key(raw) if raw else ""
            if d and d in self.protected_domains:
                return f"{d} is in an active conversation or closed deal"
        return None

    def name_hit(self, first: str, last: str) -> Optional[str]:
        key = _name_key(first, last)
        if key and key in self.full_names:
            return f"{first.strip()} {last.strip()} is already on the board"
        return None

    def probable_name_hit(self, first: str, obfuscated_last: str, company: str) -> Optional[str]:
        """
        Apollo returns obfuscated last names before enrich ("Smi***"). Same first name at the same
        company with a matching last-name prefix is a probable match. Labelled "probable" so Lia can judge.
        """
        last = (obfuscated_last or "").strip().lower()
        if "*" not in last:
            return None
        prefix = last.split("*", 1)[0]
        ck = normalize_company_key(company)
        if not prefix or not ck:
            return None
        first_l = (first or "").strip().lower()
        for board_first, board_last in self.people_by_company.get(ck, frozenset()):
            if board_first == first_l and board_last.startswith(prefix):
                return f"{first} {obfuscated_last} may match a board row at {ck}"
        return None


def _name_key(first: str, last: str) -> str:
    f = " ".join((first or "").split()).lower()
    la = " ".join((last or "").split()).lower()
    if not f or not la or "*" in la:
        return ""
    return f"{f} {la}"


def build_blocklist(
    snapshot: dict[str, Any],
    blacklist_names: set[str],
    *,
    protected_group_ids: frozenset[str] = PROTECTED_GROUP_IDS,
    protected_status_labels: frozenset[str] = PROTECTED_STATUS_LABELS,
) -> Blocklist:
    emails: set[str] = set()
    corp_domains: set[str] = set()
    company_names: set[str] = set(blacklist_names)
    full_names: set[str] = set()
    people: dict[str, set[tuple[str, str]]] = {}
    protected_companies: set[str] = set()
    protected_domains: set[str] = set()

    rows = snapshot.get("rows") or []
    for row in rows:
        name = (row.get("name") or "").strip()
        if name:
            company_names.add(name.lower())

        email = normalize_email(row.get("email") or "")
        if email:
            emails.add(email)
            dom = email_domain_key(email)
            if dom and not is_personal_email_domain(dom):
                corp_domains.add(dom)

        site = website_domain_key(row.get("website") or "")
        if site and "." in site and not is_personal_email_domain(site):
            corp_domains.add(site)

        first = (row.get("first") or "").strip()
        last = (row.get("last") or "").strip()
        key = _name_key(first, last)
        if key:
            full_names.add(key)
        ck = normalize_company_key(name)
        if ck and first and last:
            people.setdefault(ck, set()).add((first.lower(), last.lower()))

        is_protected = (row.get("group") or "") in protected_group_ids or (
            (row.get("status") or "").strip().lower() in protected_status_labels
        )
        if is_protected:
            if ck and ck not in {"unknown", "n/a", "na"}:
                protected_companies.add(ck)
            if site and "." in site and not is_personal_email_domain(site):
                protected_domains.add(site)
            em_dom = email_domain_key(email)
            if em_dom and not is_personal_email_domain(em_dom):
                protected_domains.add(em_dom)

    company_names_frozen = frozenset(company_names)
    company_keys = frozenset(k for k in (normalize_company_key(n) for n in company_names_frozen) if k)
    return Blocklist(
        emails=frozenset(emails),
        corp_domains=frozenset(corp_domains),
        company_names=company_names_frozen,
        company_keys=company_keys,
        full_names=frozenset(full_names),
        people_by_company={k: frozenset(v) for k, v in people.items()},
        protected_companies=frozenset(protected_companies),
        protected_domains=frozenset(protected_domains),
        board_rows=len(rows),
    )


# ---------------------------------------------------------------------------
# Store-facing helpers
# ---------------------------------------------------------------------------


def default_monday() -> Any:
    from monday_client import MondayClient

    return MondayClient(monday_api_key())


def ensure_snapshot(
    store: "Store",
    preset: "Preset",
    *,
    monday_factory: Optional[Callable[[], Any]] = None,
    force: bool = False,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """
    Use the stored snapshot if it is fresh; otherwise read the board once and store it.
    Returns metadata: {board_id, fetched_at, refreshed, stale_before}.
    """
    board = board_id(preset.crm)
    ttl = snapshot_ttl_hours()
    stored = store.crm_snapshot_get(board)
    stale_before = stored is None or is_stale(stored["fetched_at"], ttl, now)
    if stored is not None and not force and not stale_before:
        return {"board_id": board, "fetched_at": stored["fetched_at"], "refreshed": False, "stale_before": False}

    if monday_factory is None and not monday_api_key():
        raise CrmUnavailable("MONDAY_API_KEY is not set, so the CRM snapshot cannot be refreshed.")
    monday = (monday_factory or default_monday)()
    payload = fetch_crm_snapshot(monday, board, preset.crm)
    store.crm_snapshot_put(board, payload)
    return {"board_id": board, "fetched_at": payload["fetched_at"], "refreshed": True, "stale_before": stale_before}


def load_blocklist(store: "Store", preset: "Preset") -> Blocklist:
    """Build the blocklist from the stored snapshot and blacklist.txt. Raises if no snapshot is stored."""
    board = board_id(preset.crm)
    stored = store.crm_snapshot_get(board)
    if stored is None:
        raise CrmUnavailable("No CRM snapshot is stored yet. Start a run or press Refresh to read the board.")
    names = read_blacklist(blacklist_path(preset))
    return build_blocklist(
        stored["payload"],
        names,
        protected_group_ids=frozenset(preset.crm.protected_group_ids),
        protected_status_labels=frozenset(preset.crm.protected_status_labels),
    )


def crm_blockers(store: "Store", preset: "Preset", *, now: Optional[datetime] = None) -> list[str]:
    """Start blockers from the CRM side. Empty means a run can read the board or use a fresh snapshot."""
    board = board_id(preset.crm)
    stored = store.crm_snapshot_get(board)
    if stored is not None and not is_stale(stored["fetched_at"], snapshot_ttl_hours(), now):
        return []
    if not monday_api_key():
        if stored is None:
            return ["MONDAY_API_KEY is not set, so the CRM blocklist cannot be read."]
        return ["The CRM snapshot is stale and MONDAY_API_KEY is not set, so it cannot be refreshed."]
    return []


def live_push_enabled() -> bool:
    return os.getenv("ENGINE_LIVE_PUSH_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def _as_number(value: Any) -> float | int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).replace(",", "").replace("$", ""))
    except ValueError:
        return None


def _departments_text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(part) for part in value if part)
    return str(value or "")


def monday_item_payload(lead: dict[str, Any], contract: "CrmContract") -> tuple[str, dict[str, Any]]:
    """
    Monday column values for one approved lead.

    The item name is the shelf brand. City, State, and Country are the person's location,
    never the org HQ. A Florida person at a New York HQ brand stays a Florida row.
    """
    person = lead.get("person") or {}
    org = person.get("organization") or {}
    cols = contract.columns
    email = (lead.get("email") or "").strip()
    item_name = (lead.get("shelf_brand") or org.get("name") or "Unknown").strip() or "Unknown"
    website = (org.get("website_url") or org.get("primary_domain") or "").strip()
    values: dict[str, Any] = {
        cols["first_name"]: (person.get("first_name") or "").strip(),
        cols["last_name"]: (person.get("last_name") or "").strip(),
        cols["email"]: {"email": email, "text": email},
        cols["title"]: lead.get("title") or "",
        cols["contact_type"]: {"labels": ["Contact"]},
        cols["seniority"]: person.get("seniority") or "",
        cols["departments"]: _departments_text(person.get("departments")),
        cols["website"]: website,
        cols["linkedin"]: person.get("linkedin") or person.get("linkedin_url") or "",
        cols["city"]: person.get("city") or "",
        cols["state"]: person.get("state") or "",
        cols["country"]: person.get("country") or "",
        cols["vertical"]: {"labels": [lead.get("vertical") or ""]},
        cols["status"]: {"label": "Uncontacted"},
    }
    revenue = _as_number(org.get("annual_revenue"))
    if revenue is not None:
        values[cols["annual_revenue"]] = revenue
    notes = " ".join(str(item) for item in (lead.get("evidence") or []) if item).strip()
    if notes and cols.get("notes"):
        values[cols["notes"]] = notes[:500]
    return item_name, values


def _label_names(column: dict[str, Any]) -> set[str]:
    raw = column.get("settings_str") if column.get("settings_str") is not None else column.get("settings")
    if isinstance(raw, str):
        try:
            settings = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            return set()
    elif isinstance(raw, dict):
        settings = raw
    else:
        return set()
    labels = settings.get("labels")
    names: set[str] = set()
    if isinstance(labels, dict):
        values = labels.values()
    elif isinstance(labels, list):
        values = labels
    else:
        return set()
    for value in values:
        if isinstance(value, str) and value.strip():
            names.add(value.strip().lower())
        elif isinstance(value, dict) and str(value.get("name") or "").strip():
            names.add(str(value["name"]).strip().lower())
    return names


# Monday column titles on The Underline board, matched without case or extra spaces.
_COLUMN_TITLES: dict[str, tuple[str, ...]] = {
    "first_name": ("first name",),
    "last_name": ("last name",),
    "email": ("email",),
    "title": ("title",),
    "contact_type": ("record type", "contact type"),
    "seniority": ("seniority",),
    "departments": ("departments",),
    "website": ("website",),
    "linkedin": ("person linkedin url", "linkedin"),
    "annual_revenue": ("annual revenue",),
    "city": ("city",),
    "state": ("state",),
    "country": ("country",),
    "vertical": ("vertical",),
    "status": ("lead status", "status"),
    "notes": ("notes",),
}


def _norm_title(value: str) -> str:
    return " ".join(value.strip().lower().split())


def columns_from_board(metadata: dict[str, Any] | None) -> tuple[dict[str, str], list[str]]:
    """Map the engine's columns onto a live board by title. The second list is missing titles."""
    titled: dict[str, str] = {}
    for col in (metadata or {}).get("columns") or []:
        title = _norm_title(str(col.get("title") or ""))
        column_id = str(col.get("id") or "").strip()
        if title and column_id and title not in titled:
            titled[title] = column_id
    mapped: dict[str, str] = {}
    missing: list[str] = []
    for logical, names in _COLUMN_TITLES.items():
        found = next((titled[name] for name in names if name in titled), "")
        if found:
            mapped[logical] = found
        else:
            missing.append(names[0])
    return mapped, missing


def vertical_labels_for(preset: "Preset") -> list[str]:
    """Every Vertical label a push from this preset can write."""
    from prospecting_config import MONDAY_VERTICAL_LABELS

    labels = set(MONDAY_VERTICAL_LABELS)
    for vertical in preset.verticals:
        if vertical.monday_vertical != "from_research":
            labels.add(vertical.monday_vertical)
    return sorted(labels)


def validate_board_contract(metadata: dict[str, Any] | None, preset: "Preset") -> list[str]:
    """
    Named problems with the live board. Empty means the columns, the New Leads group,
    and the labels a push writes are all present. The snapshot file is not consulted.
    """
    if not metadata:
        return ["Monday did not return the board, so the contract could not be checked."]
    problems: list[str] = []
    contract = preset.crm
    columns = {str(col.get("id")): col for col in (metadata.get("columns") or []) if col.get("id")}
    for logical, column_id in contract.columns.items():
        if column_id not in columns:
            problems.append(f"Missing column {logical} ({column_id}).")

    group_id = new_leads_group_id(contract)
    group_ids = {str(group.get("id")) for group in (metadata.get("groups") or []) if group.get("id")}
    if group_id not in group_ids:
        problems.append(f"Missing New Leads group {group_id}.")

    required = {
        "status": ["Uncontacted"],
        "contact_type": ["Contact"],
        "vertical": vertical_labels_for(preset),
    }
    for logical, needed in required.items():
        column_id = contract.columns.get(logical)
        column = columns.get(column_id or "")
        if column is None:
            continue
        present = _label_names(column)
        if not present:
            problems.append(f"Column {logical} ({column_id}) has no labels, so {needed[0]} cannot be confirmed.")
            continue
        for label in needed:
            if label.strip().lower() not in present:
                problems.append(f"Column {logical} ({column_id}) is missing the label {label}.")
    return problems


def check_board_contract(monday: Any, preset: "Preset") -> list[str]:
    meta = monday.get_board_metadata(int(board_id(preset.crm)))
    return validate_board_contract(meta, preset)


def remember_board_email(store: "Store", preset: "Preset", *, email: str, shelf_brand: str) -> None:
    """Add a just-created row to the stored snapshot so the next lead in this push sees the email."""
    board = board_id(preset.crm)
    stored = store.crm_snapshot_get(board)
    if stored is None:
        return
    payload = dict(stored["payload"])
    rows = list(payload.get("rows") or [])
    rows.append(
        {
            "name": shelf_brand,
            "email": normalize_email(email),
            "website": "",
            "status": "Uncontacted",
            "first": "",
            "last": "",
            "group": new_leads_group_id(preset.crm),
        }
    )
    payload["rows"] = rows
    store.crm_snapshot_put(board, payload)


def crm_status(store: "Store", preset: "Preset", *, now: Optional[datetime] = None) -> dict[str, Any]:
    """What the Gather screen shows: when the board was read, how old it is, and whether it is stale."""
    board = board_id(preset.crm)
    ttl = snapshot_ttl_hours()
    stored = store.crm_snapshot_get(board)
    out: dict[str, Any] = {
        "board_id": board,
        "ttl_hours": ttl,
        "monday_key_set": bool(monday_api_key()),
        "fetched_at": None,
        "age_hours": None,
        "stale": True,
        "board_rows": 0,
    }
    if stored is not None:
        out["fetched_at"] = stored["fetched_at"]
        out["age_hours"] = round(snapshot_age_hours(stored["fetched_at"], now), 2)
        out["stale"] = is_stale(stored["fetched_at"], ttl, now)
        out["board_rows"] = len(stored["payload"].get("rows") or [])
    return out
