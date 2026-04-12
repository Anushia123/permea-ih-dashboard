"""
Fetch Lemlist campaign sequence stats for the Insight Hub dashboard.

Requires env var: LEMLIST_API_KEY (from Lemlist Settings → Integrations → API)
Optional env var: LEMLIST_CAMPAIGN_NAME (filter campaigns by name, default: "Permea IH Free Trial Campaign")

Auth:  HTTP Basic Auth — empty username, API key as password
Stats: GET /api/v2/campaigns/{id}/stats?startDate=...&endDate=...
       (v1 campaign endpoints return metadata only — no stats)

Confirmed response fields (from developer.lemlist.com):
  messagesSent, messagesNotSent, messagesBounced, delivered,
  opened, clicked, replied, nbLeadsUnsubscribed
"""

import os
import json
import sys
import requests
from datetime import datetime, timezone, timedelta

API_BASE        = "https://api.lemlist.com/api"
CAMPAIGN_FILTER = os.environ.get("LEMLIST_CAMPAIGN_NAME", "Permea IH Free Trial Campaign")

# Campaign window — match the PostHog lookback window
DAYS_LOOKBACK = int(os.environ.get("LEMLIST_DAYS_LOOKBACK", "90"))
DATE_FROM = (datetime.now(timezone.utc) - timedelta(days=DAYS_LOOKBACK)).strftime("%Y-%m-%dT00:00:00.000Z")
DATE_TO   = datetime.now(timezone.utc).strftime("%Y-%m-%dT23:59:59.999Z")

api_key = os.environ.get("LEMLIST_API_KEY")
if not api_key:
    print("✗ LEMLIST_API_KEY environment variable is not set", file=sys.stderr)
    sys.exit(1)

# Lemlist uses HTTP Basic Auth: empty username, API key as password
AUTH = ("", api_key)


def get(path, params=None):
    """GET a Lemlist API endpoint. Raises on HTTP errors."""
    resp = requests.get(f"{API_BASE}{path}", auth=AUTH, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_campaign_stats(campaign_id, campaign_name):
    """
    Fetch stats for one campaign using the v2 stats endpoint.
    Returns dict with the fields build_metrics.py expects.
    """
    try:
        data = get(f"/v2/campaigns/{campaign_id}/stats", params={
            "startDate": DATE_FROM,
            "endDate":   DATE_TO,
        })
        stats = {
            "sent":         int(data.get("messagesSent",        0)),
            "opened":       int(data.get("opened",              0)),
            "clicked":      int(data.get("clicked",             0)),
            "replied":      int(data.get("replied",             0)),
            "bounced":      int(data.get("messagesBounced",     0)),
            "unsubscribed": int(data.get("nbLeadsUnsubscribed", 0)),
        }
        print(f"  ✓ '{campaign_name}': sent={stats['sent']}, opened={stats['opened']}, "
              f"clicked={stats['clicked']}, replied={stats['replied']}", file=sys.stderr)
        return stats

    except requests.HTTPError as e:
        print(f"  ✗ HTTP {e.response.status_code} for '{campaign_name}': {e}", file=sys.stderr)
    except Exception as e:
        print(f"  ✗ Error fetching stats for '{campaign_name}': {e}", file=sys.stderr)

    return {"sent": 0, "opened": 0, "clicked": 0, "replied": 0, "bounced": 0, "unsubscribed": 0}


def main():
    print("→ Fetching Lemlist metrics…", file=sys.stderr)
    print(f"  Campaign filter: '{CAMPAIGN_FILTER}'", file=sys.stderr)
    print(f"  Date range: {DATE_FROM[:10]} → {DATE_TO[:10]}", file=sys.stderr)

    # ── Step 1: list all campaigns (v1 list endpoint is fine for names/IDs)
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

    all_names = [c.get("name", c.get("_id")) for c in campaigns]
    print(f"  ✓ Found {len(campaigns)} total campaigns", file=sys.stderr)

    ih_campaigns = [
        c for c in campaigns
        if CAMPAIGN_FILTER.lower() in c.get("name", "").lower()
    ]

    if not ih_campaigns:
        print(f"  ! No campaigns matching '{CAMPAIGN_FILTER}'", file=sys.stderr)
        print(f"  ! Available: {all_names}", file=sys.stderr)
    else:
        print(f"  ✓ Matched {len(ih_campaigns)} campaigns: {[c.get('name') for c in ih_campaigns]}", file=sys.stderr)

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

    # ── Step 2: fetch v2 stats for each matching campaign
    for c in ih_campaigns:
        cid   = c.get("_id")
        name  = c.get("name", cid)
        stats = get_campaign_stats(cid, name)

        totals["sent"]         += stats["sent"]
        totals["opened"]       += stats["opened"]
        totals["clicked"]      += stats["clicked"]
        totals["replied"]      += stats["replied"]
        totals["bounced"]      += stats["bounced"]
        totals["unsubscribed"] += stats["unsubscribed"]

        totals["campaigns"].append({
            "name":       name,
            "sent":       stats["sent"],
            "open_rate":  round((stats["opened"]  / max(stats["sent"],   1)) * 100, 1),
            "ctr":        round((stats["clicked"] / max(stats["opened"], 1)) * 100, 1),
            "reply_rate": round((stats["replied"] / max(stats["sent"],   1)) * 100, 1),
        })

    # ── Step 3: compute aggregate rates
    if totals["sent"] > 0:
        totals["open_rate"]  = round((totals["opened"]  / totals["sent"])            * 100, 1)
        totals["ctr"]        = round((totals["clicked"] / max(totals["opened"], 1))  * 100, 1)
        totals["reply_rate"] = round((totals["replied"] / totals["sent"])            * 100, 1)
    else:
        totals["open_rate"] = totals["ctr"] = totals["reply_rate"] = 0

    print(f"  ✓ Totals: sent={totals['sent']}, open_rate={totals['open_rate']}%, "
          f"ctr={totals['ctr']}%, replies={totals['replied']}", file=sys.stderr)

    print(json.dumps(totals, indent=2))


if __name__ == "__main__":
    main()
