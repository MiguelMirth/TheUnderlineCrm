# Agent notes — The Underline

Operating contract for Cursor and other agents. Product and ops truth: [`README.md`](README.md). Env names: [`.env.example`](.env.example).

## SSOT

- Update **README.md** when you add a script, pipeline, board field, or operator command.
- Update **.env.example** when you add or rename an env var.
- Do **not** create new `PROJECT_CONTEXT`, `HANDOFF_*`, or feature `.md` files. Dated HITL reports belong under `data/outputs/` or `data/archive/` only.

If README and code disagree, **code defaults win** — then fix the README in the same change.

## Safety

- Default is dry-run. Do not pass `--live` or `--apply` unless the user explicitly asks.
- Do not commit `.env`, Gmail OAuth JSON, or API keys.
- Do not paste inbound email bodies into Monday Notes (triage writes a short `notes_summary`).
- Do not delete Monday rows without a reviewed HITL CSV from `src/active_outreach_cleanup.py`.
- Do not git commit or push unless the user asks.

## Prospecting quality (Lia bar)

- Monday item name = **shelf brand**, not the holding company.
- Prefer sponsorship / brand / experiential titles; block agencies, market research, `.edu`, federal, non-sponsor healthcare ([`src/prospecting_qa.py`](src/prospecting_qa.py)).
- Concert Series Email 1 is Miami Music Series copy — not Levitt re-engagement templates.
- Email 2–3 stay in the Email 1 thread; 4–5 start a new thread.

## Do not resurrect

Vertical Apollo rotation, US brand catalogs, Gemini target-list prospecting, parent-sponsor seed CLIs, and local funnel dashboards were removed. See README “Do not resurrect”.

## Where to look

| Need | File |
|------|------|
| Operator commands | `README.md` |
| QA gates | `src/prospecting_qa.py` |
| Prospecting engine | `src/engine/`, `web/`, README “Prospecting engine” |
| Apollo people search helpers | `src/apollo_client.py` |
| Sponsor research helpers | `src/sponsor_research.py` |
| Copy | `data/underline templates.txt` |
| Blocklist | `data/inputs/blacklist.txt` |
| Board IDs | env defaults in `src/monday_client.py`, `src/send_followups_email1.py`, `src/reply_triage_monday.py` |
