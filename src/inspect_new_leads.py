import json
import os
import sys
from collections import defaultdict
from dotenv import load_dotenv

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)
PROJECT_ROOT = os.path.dirname(current_dir)

from monday_client import MondayClient

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

MONDAY_API_KEY = os.getenv("MONDAY_API_KEY", "").strip()
MASTER_BOARD_ID = int(os.getenv("MASTER_BOARD_ID", "18401545002"))
NEW_LEADS_GROUP_ID = os.getenv("NEW_LEADS_GROUP_ID", "group_mm0xbmrj")

SNAPSHOT_FILE = os.getenv("SNAPSHOT_FILE", os.path.join("data", "outputs", "new_leads_snapshot.json"))
SUMMARY_FILE = os.getenv("SUMMARY_FILE", os.path.join("data", "outputs", "new_leads_summary.txt"))

if not os.path.isabs(SNAPSHOT_FILE):
    SNAPSHOT_FILE = os.path.join(PROJECT_ROOT, SNAPSHOT_FILE)
if not os.path.isabs(SUMMARY_FILE):
    SUMMARY_FILE = os.path.join(PROJECT_ROOT, SUMMARY_FILE)

IMPORTANT_COLUMNS = {
    "name": "Item Name (Company)",
    "text_mm0xjngp": "First Name",
    "text_mm0xg7qz": "Last Name",
    "text_mm0xg2xb": "Title",
    "email_mm0xb00t": "Email",
    "text_mm0xyyzh": "LinkedIn",
    "text_mm0xt1wm": "Website",
    "text_mm0xkdyw": "City",
    "text_mm0xrszg": "State",
    "text_mm0x4tb7": "Country",
    "numeric_mm0x7xfb": "Annual Revenue",
    "dropdown_mm0xx10b": "Vertical",
    "status": "Lead Status",
    "dropdown_mm0x5x0q": "Record Type",
    "text_mm0x49y": "Seniority",
    "text_mm0xcyag": "Departments",
}


def to_column_map(item):
    result = {"name": item.get("name", "")}
    for cv in item.get("column_values", []):
        result[cv.get("id")] = cv.get("text")
    return result


def main():
    if not MONDAY_API_KEY:
        raise RuntimeError("Missing MONDAY_API_KEY. Set it in your environment or .env file.")

    monday = MondayClient(MONDAY_API_KEY)
    print("Fetching board items with columns...")
    items = monday.get_board_items_with_columns(MASTER_BOARD_ID, limit=500)

    new_leads = []
    for item in items:
        group = item.get("group") or {}
        if group.get("id") == NEW_LEADS_GROUP_ID:
            new_leads.append(item)

    print(f"Found {len(new_leads)} items in New Leads group.")

    snapshot = []
    missing_counts = defaultdict(int)

    for item in new_leads:
        row = to_column_map(item)
        trimmed = {}
        for col_id, label in IMPORTANT_COLUMNS.items():
            value = row.get(col_id, "")
            trimmed[label] = value if value is not None else ""
            if not trimmed[label]:
                missing_counts[label] += 1
        snapshot.append(trimmed)

    os.makedirs(os.path.dirname(SNAPSHOT_FILE), exist_ok=True)
    with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)

    os.makedirs(os.path.dirname(SUMMARY_FILE), exist_ok=True)
    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        f.write(f"New Leads count: {len(snapshot)}\n\n")
        f.write("Missing values by field:\n")
        for label in IMPORTANT_COLUMNS.values():
            f.write(f"- {label}: {missing_counts[label]} missing\n")

    print(f"Wrote {SNAPSHOT_FILE} and {SUMMARY_FILE}")


if __name__ == "__main__":
    main()
