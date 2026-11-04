---
name: check-meeting-notes
description: Check the team's Google Docs meeting notes for the XOM caustic soda project, find entries added since the last check, and turn them into action items mapped to this repo (model.py, routing.py, config.py, modes.csv, network.xlsx, ...). Use this whenever the user asks what changed in the meeting notes, what XOM/Exxon/the sponsor asked for, what's new since the last meeting, what to work on next, or wants to prep for or follow up on a sponsor meeting, even if they don't say "meeting notes".
---

# Check meeting notes

The team keeps one running Google Doc of meeting notes, newest entry at the top. XOM's asks in those meetings drive what goes into the model, so the useful output is not a summary of the doc. It's a list of what's new, what each item means for the code or data, and whether the repo already handles it.

## 1. Find the notes

The main doc is **"Meeting Notes"** (owned by a teammate, in the shared project folder):

- File ID: `17FbPqy_HaIkwYxWtilyG9n9ABpotl41fdItM8IXVukg`
- Read it with the Google Drive connector's `read_file_content`. If that ID fails, search with `title contains 'Meeting Notes'` and pick the one in the same folder as "Brenntag notes".

Also look for other docs in that folder modified since the last check (`parentId = '1GS4H0azm8mxWMQmC1bbeS5bhrP7oPEkc' and modifiedTime > '<last check>'`). Teammates sometimes put meeting or vendor notes in separate files. Skim those too.

Entries start with a dated heading like `# **10/28/2026 - Meeting with Exxon**` or `# **10/22/2026 - Internal Team Meeting**`. "Meeting with Exxon/ExxonMobil" entries carry the sponsor's asks. Internal entries carry the team's own plans and TODOs.

## 2. Work out what's new

Last-check state lives in `.claude/meeting-notes-state.json` (gitignored, per person):

```json
{"last_checked": "2026-10-28", "last_entry_seen": "10/28/2026 - Meeting with Exxon"}
```

- If the file exists, treat entries dated after `last_checked` as new. Also treat as new the entry named in `last_entry_seen` if the doc's modified time is later than `last_checked`, since notes often get filled in after the meeting.
- If it doesn't exist, use the most recent XOM meeting entry plus any internal entries after it.
- When you're done, update the file. It stays local, so it never conflicts between teammates.

## 3. Check each item against the repo

Before you label an item, check the code rather than guessing. The user wants to know what's actually left to do. Typical mappings:

| Kind of ask | Where it lands |
|---|---|
| Freight rates, $/MT, wet vs. dry, rail/barge/truck costs | `config.py` (`MODE_PARAMS`, `HANDLING_USD_PER_TON`, `SOLUTION_STRENGTH`), `routing.py`, `lane_rates.csv` (quoted overrides) |
| Which modes a site has, new rail/barge builds, mode share limits | `modes.csv`, `network.py`, `model.py` |
| New sites, terminals, intermediate hubs (e.g., Chicago), volumes | `network.xlsx` (Sources/Sinks/Intermediates sheets), `loader.py` |
| Routes, distances, specific rail lines | `build_distances.py`, `lane_distances.csv` |
| Sensitivity ("what rate makes Canada feasible?") | `sensitivity.py` |
| Supplier prices, arbitrage, global/import scenarios | not modeled yet (no price data in the model) |

Status for each item: **done** (point to file:line), **partial** (say what's missing), **not started**, or **data needed from XOM**.

## 4. Report

Keep it short, because it's usually read right before or after a meeting:

1. **New since last check:** one line per new entry (date and type).
2. **Action items:** a table with columns ask | from (XOM or team) | maps to | status | next step. Put XOM asks first. They're what the sponsor will follow up on.
3. **Data we're waiting on / owe:** things XOM promised, or questions we need to send them.
4. **Contradictions:** any place the new notes conflict with what the model assumes now (units, which supplier serves which site, mode availability). These are the costly ones to miss.

Offer to start on the top item, but don't edit code or the doc unless asked.

## Notes

- The doc lists people's contact details (phone numbers, emails). Don't repeat them in reports or files. Refer to people by role ("XOM sponsor") or first name, the way the notes do.
- Under Rice's data guidance, if notes ever contain student records, health information or card numbers, give a brief reminder and leave those details out.
- Don't edit the Google Doc. It's shared notes owned by a teammate.
