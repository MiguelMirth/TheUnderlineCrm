# Data

Folder map only. System docs: [README.md](../README.md).

| Path | Role |
|------|------|
| `inputs/` | Seeds and blocklists: `miami_events_seed.json`, `blacklist.txt`, `underline_known_partners.json`. `underline_park_segments_seed.json` is leftover unused data. |
| `outputs/` | Active run artifacts (research JSON, HITL CSV/MD, email candidate dumps). Dated `research_*` files are gitignored. |
| `archive/` | Frozen HITL / cleanup bundles after a job is done |
| `engine/` | Prospecting engine SQLite database (`underline.db`), WAL files, and `backups/`. Gitignored. Created by the app. |
| `underline templates.txt` | Outreach copy (emails 1–5 + Levitt re-engagement) |
| `*.pdf` | Optional decks for Cursor fit scoring (`underline_knowledge.py`) |

New events are added from the engine when Discover new events is on. Do not store new living docs here.
