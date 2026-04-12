"""
Fetch Lemlist campaign sequence stats for the Insight Hub dashboard.

Requires env var: LEMLIST_API_KEY (from Lemlist Settings → Integrations → API)
Optional env var: LEMLIST_CAMPAIGN_NAME (filter campaigns by name, default: "Insight Hub")

Auth: HTTP Basic Auth — empty username, API key as password.
API:  https://api.lemlist.com/api  (v1)

Confirmed field names (update this comment after first live run):
  Campaign list:  GET /api/campaigns → array of campaign objects
  Campaign stats: GET /api/campaigns/{id} → stat fields TBC from first run

Stat field name candidates (Lemlist has changed these across versions):
  v1 old: emailsSent, emailsOpened, emailsClicked, emailsReplied, emailsBounced, emailsUnsubscribed
  v1 new: sendCount, openCount, clickCount, replyCount, bounceCount, unsubscribeCount
  flat:   sent, opened, clicked, replied, bounced, unsubscribed
  Script tries all three — first non-zero wins.
"""

import os
import json
import sys
import requests
from datetime import datetime, timezone

API_BASE        = "https://api.lemlist.com/api"
CAMPAIGN_FILTER = os.environ.get("LEMLIST_CAMPAIGN_NAME", "Insight Hub")

api_key = os.environ.get("LEMLIST_API_KEY")
if not api_key:
    print("✗ LEMLIST_API_KEY environment variable is not set", file=sys.stderr)
    sys.exit(1)

# Lemlist uses HTTP Basic Auth: empty username, API key as password
AUTH = ("", api_key)


def get(path):
    """GET a Lemlist API endpoint. Raises on HTTP errors."""
    resp = requests.get(f"{API_BASE}{path}", auth=AUTH, timeout=30)
    resp.raise_for_status()
    return resp.json()


def extract_stat(obj, *keys):
    """
    Try multiple candidate key names for the same stat.
    Returns first non-None value found, or 0.
    Used because Lemlist has renamed fields across API versions.
    """
    for key in keys:
        val = obj.get(key)
        if val is not None:
            return int(val)
    return 0


def main():
    print("→ Fetching Lemlist metrics…", file=sys.stderr)
    print(f"  Campaign filter: '{CAMPAIGN_FILTER}'", file=sys.stderr)

    # ── Step 1: list all campaigns
    try:
        campaigns = get("/campaigns")
    except Exception as e:
        print(f"  ✗ Could not list campaigns: {e}", file=sys.stderr)
        print(json.dumps({"source": "lemlist", "error": str(e),
                          "sent": 0, "opened": 0, "clicked": 0,
                          "replied": 0, "bounced": 0, "unsubscribed": 0,
                          "open_rate": 0, "ctr": 0, "reply_rate": 0,
                          "campaigns": []}))
        return

    # Always log all campaign names so we can verify the filter is matching
    all_names = [c.get("name", c.get("_id")) for c in campaigns]
    print(f"  ✓ Found {len(campaigns)} total campaigns: {all_names}", file=sys.stderr)

    ih_campaigns = [
        c for c in campaigns
        if CAMPAIGN_FILTER.lower() in c.get("name", "").lower()
    ]

    if not ih_campaigns:
        print(f"  ! No campaigns matching '{CAMPAIGN_FILTER}' — outputting zeros.", file=sys.stderr)
        print(f"  ! To fix: set LEMLIST_CAMPAIGN_NAME env var to match one of the names above.", file=sys.stderr)

    totals = {
        "source":       "lemlist",
        "fetched_at":   datetime.now(timezone.utc).isoformat(),
        "sent":         0,
        "opened":       0,
        "clicked":      0,
        "replied":      0,
        "bounced":      0,
        "unsubscribed": 0,
        "campaigns":    [],
    }

    # ── Step 2: fetch stats for each matching campaign
    for c in ih_campaigns:
        cid  = c.get("_id")
        name = c.get("name", cid)
        try:
            data = get(f"/campaigns/{cid}")

            # Stats may live at the top level or nested under 'statistic'
            s = data.get("statistic", data)

            # Log raw keys on first campaign so we can verify field names
            if not totals["campaigns"]:
                print(f"  DEBUG raw stat keys for '{name}': {list(s.keys())}", file=sys.stderr)

            # Try all known field name variants
            sent   = extract_stat(s, "sendCount",        "emailsSent",         "sent")
            opened = extract_stat(s, "openCount",         "emailsOpened",       "opened")
            clicked= extract_stat(s, "clickCount",        "emailsClicked",      "clicked")
            replied= extract_stat(s, "replyCount",        "emailsReplied",      "replied")
            bounced= extract_stat(s, "bounceCount",       "emailsBounced",      "bounced")
            unsub  = extract_stat(s, "unsubscribeCount",  "emailsUnsubscribed", "unsubscribed")

            totals["sent"]         += sent
            totals["opened"]       += opened
            totals["clicked"]      += clicked
            totals["replied"]      += replied
            totals["bounced"]      += bounced
            totals["unsubscribed"] += unsub

            totals["campaigns"].append({
                "name":       name,
                "sent":       sent,
                "open_rate":  round((opened  / max(sent,   1)) * 100, 1),
                "ctr":        round((clicked / max(opened, 1)) * 100, 1),
                "reply_rate": round((replied / max(sent,   1)) * 100, 1),
            })
            print(f"  ✓ '{name}': sent={sent}, opened={opened}, clicked={clicked}, replied={replied}", file=sys.stderr)

        except Exception as e:
            print(f"  ✗ Error fetching stats for '{name}': {e}", file=sys.stderr)

    # ── Step 3: compute totals
    total_sent   = totals["sent"]   or 1   # avoid division by zero in rate calcs
    total_opened = totals["opened"] or 1

    totals["open_rate"]  = round((totals["opened"]  / total_sent)   * 100, 1)
    totals["ctr"]        = round((totals["clicked"] / total_opened) * 100, 1)
    totals["reply_rate"] = round((totals["replied"] / total_sent)   * 100, 1)

    # Zero out rates when there was genuinely no data (avoids misleading 0/1=0%)
    if totals["sent"] == 0:
        totals["open_rate"] = totals["ctr"] = totals["reply_rate"] = 0

    print(f"  ✓ Totals: sent={totals['sent']}, open_rate={totals['open_rate']}%, "
          f"ctr={totals['ctr']}%, replies={totals['replied']}", file=sys.stderr)

    print(json.dumps(totals, indent=2))


if __name__ == "__main__":
    main()
