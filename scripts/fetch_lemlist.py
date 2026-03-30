"""
Fetch Lemlist campaign sequence stats for the Insight Hub dashboard.

Requires env var: LEMLIST_API_KEY (from Lemlist Settings → Integrations → API)
Optional env var: LEMLIST_CAMPAIGN_NAME (filter campaigns by name, default: "Insight Hub")
"""

import os
import json
import sys
import requests
from datetime import datetime, timezone

API_BASE = "https://api.lemlist.com/api"
CAMPAIGN_FILTER = os.environ.get("LEMLIST_CAMPAIGN_NAME", "Insight Hub")

# Lemlist uses HTTP Basic Auth with the API key as the password
AUTH = ("", os.environ["LEMLIST_API_KEY"])


def fetch_campaigns():
    """List all Lemlist campaigns."""
    resp = requests.get(f"{API_BASE}/campaigns", auth=AUTH, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_campaign_stats(campaign_id):
    """Get stats for a specific campaign."""
    resp = requests.get(f"{API_BASE}/campaigns/{campaign_id}", auth=AUTH, timeout=30)
    resp.raise_for_status()
    return resp.json()


def main():
    print("→ Fetching Lemlist metrics…", file=sys.stderr)

    try:
        campaigns = fetch_campaigns()
    except Exception as e:
        print(f"  ✗ Lemlist: could not list campaigns: {e}", file=sys.stderr)
        print(json.dumps({"source": "lemlist", "error": str(e), "sent": 0}))
        return

    ih_campaigns = [
        c for c in campaigns
        if CAMPAIGN_FILTER.lower() in c.get("name", "").lower()
    ]

    if not ih_campaigns:
        print(f"  ! Lemlist: no campaigns matching '{CAMPAIGN_FILTER}'", file=sys.stderr)
        print(f"  ! Available: {[c.get('name') for c in campaigns[:10]]}", file=sys.stderr)

    totals = {
        "source": "lemlist",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sent": 0,
        "opened": 0,
        "clicked": 0,
        "replied": 0,
        "bounced": 0,
        "unsubscribed": 0,
        "campaigns": [],
    }

    for c in ih_campaigns:
        cid  = c.get("_id")
        name = c.get("name", cid)
        try:
            stats = fetch_campaign_stats(cid)
            s = stats.get("statistic", stats)  # some versions nest under 'statistic'

            sent        = s.get("emailsSent", s.get("sent", 0))
            opened      = s.get("emailsOpened", s.get("opened", 0))
            clicked     = s.get("emailsClicked", s.get("clicked", 0))
            replied     = s.get("emailsReplied", s.get("replied", 0))
            bounced     = s.get("emailsBounced", s.get("bounced", 0))
            unsub       = s.get("emailsUnsubscribed", s.get("unsubscribed", 0))

            totals["sent"]          += sent
            totals["opened"]        += opened
            totals["clicked"]       += clicked
            totals["replied"]       += replied
            totals["bounced"]       += bounced
            totals["unsubscribed"]  += unsub

            totals["campaigns"].append({
                "name":      name,
                "sent":      sent,
                "open_rate": round((opened / max(sent, 1)) * 100, 1),
                "ctr":       round((clicked / max(opened, 1)) * 100, 1),
                "reply_rate": round((replied / max(sent, 1)) * 100, 1),
            })
            print(f"  ✓ Lemlist: '{name}' (sent={sent}, open_rate={round((opened/max(sent,1))*100,1)}%)", file=sys.stderr)

        except Exception as e:
            print(f"  ✗ Lemlist: error fetching '{name}': {e}", file=sys.stderr)

    sent = totals["sent"] or 1
    totals["open_rate"] = round((totals["opened"] / sent) * 100, 1)
    totals["ctr"]       = round((totals["clicked"] / max(totals["opened"], 1)) * 100, 1)
    totals["reply_rate"] = round((totals["replied"] / sent) * 100, 1)

    print(json.dumps(totals, indent=2))


if __name__ == "__main__":
    main()
