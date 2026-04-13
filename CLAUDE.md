# Permea IH Dashboard — Claude Instructions

## Auto-refresh CIO metrics on session start

At the start of every session in this project, do the following **before responding to the user's first message**:

1. Read `data/manual_overrides.json`
2. Check the `cio_journeys.pta.last_updated` date
3. If it is **not today's date**, automatically:
   - Fetch metrics for all 3 CIO campaigns using the Customer.io MCP tool (`mcp__claude_ai_Customer_io__metrics`, action "fetch"):
     - Campaign 54 (PTA), workspace 173732, time_range start 2026-03-01 to today, human_only true
     - Campaign 55 (Core Journey), same params
     - Campaign 57 (Urgency Journey), same params
   - Update `data/manual_overrides.json` — cio_journeys section only:
     - Map: sent=total_sent, opened=total_opened, clicked=total_clicked, open_rate=open_rate, ctr=click_rate
     - Set last_updated to today's date (YYYY-MM-DD)
     - Leave all other fields unchanged
   - Commit and push:
     ```
     git add data/manual_overrides.json
     git diff --staged --quiet || git commit -m "chore: refresh CIO journey metrics [DATE]"
     git pull origin main --no-rebase && git push origin main
     ```
   - Notify the user with one line: e.g. "CIO metrics refreshed — PTA: 5 sent, 80% open, 40% CTR"
4. If already up to date, do nothing and do not mention it.

## Project context

- Repo: `/Users/anushia.yaqoob/permea-ih-dashboard`
- Dashboard: `https://anushia123.github.io/permea-ih-dashboard`
- CIO workspace: 173732 (EU)
- Full project state: read memory files in `~/.claude/projects/-Users-anushia-yaqoob-permea-ih-dashboard/memory/`
