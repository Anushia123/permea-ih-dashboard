"""
Fetch Lemlist campaign sequence stats for the Insight Hub dashboard.

Requires env var: LEMLIST_API_KEY (from Lemlist Settings → Integrations → API)
Optional env var: LEMLIST_CAMPAIGN_NAME (filter campaigns by name, default: "Permea IH Free Trial Campaign")

Auth: HTTP Basic Auth — empty username, API key as password.
API:  https://api.lemlist.com/api  (v1)

Confirmed from first live run (2026-04-12):
  GET /api/campaigns/{id} returns only metadata — no stats
  Stats are at: GET /api/campaigns/{id}/export/leads-stats (one row per lead)
  OR stats are embedded in the /api/campaigns list response
"""

import os
import json
import sys
import requests
from datetime import datetime, timezone

API_BASE        = "https://api.lemlist.com/api"
CAMPAIGN_FILTER = os.environ.get("LEMLIST_CAMPAIGN_NAME", "Permea IH Free Trial Campaign")

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


def extract_stat(obj, *keys):
    """Try multiple candidate key names, return first non-None as int."""
    for key in keys:
        val = obj.get(key)
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                pass
    return 0


def get_campaign_stats(campaign_id, campaign_name):
    """
    Try multiple Lemlist endpoints to get campaign stats.
    Returns dict with sent/opened/clicked/replied/bounced/unsubscribed.
    """
    zero = {"sent": 0, "opened": 0, "clicked": 0, "replied": 0, "bounced": 0, "unsubscribed": 0}

    # Attempt 1: dedicated stats endpoint
    for stats_path in [
        f"/campaigns/{campaign_id}/stats",
        f"/campaigns/{campaign_id}/statistics",
    ]:
        try:
            data = get(stats_path)
            print(f"  DEBUG {stats_path} keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}", file=sys.stderr)
            s = data.get("statistic", data) if isinstance(data, dict) else {}
            sent = extract_stat(s,
                "sendCount", "emailsSent", "sent",
                "contactedCount", "totalSent", "messagesCount",
            )
            if sent > 0:
                print(f"  ✓ Stats from {stats_path}", file=sys.stderr)
                return {
                    "sent":         sent,
                    "opened":       extract_stat(s, "openCount",        "emailsOpened",       "opened",       "openedCount"),
                    "clicked":      extract_stat(s, "clickCount",        "emailsClicked",      "clicked",      "clickedCount"),
                    "replied":      extract_stat(s, "replyCount",        "emailsReplied",      "replied",      "repliedCount"),
                    "bounced":      extract_stat(s, "bounceCount",       "emailsBounced",      "bounced",      "bouncedCount"),
                    "unsubscribed": extract_stat(s, "unsubscribeCount",  "emailsUnsubscribed", "unsubscribed", "unsubscribedCount"),
                }
        except requests.HTTPError as e:
            print(f"  ! {stats_path} → {e.response.status_code}", file=sys.stderr)
        except Exception as e:
            print(f"  ! {stats_path} → {e}", file=sys.stderr)

    # Attempt 2: individual campaign endpoint — check sendDetails
    try:
        data = get(f"/campaigns/{campaign_id}")
        send_details = data.get("sendDetails", {})
        if send_details:
            print(f"  DEBUG sendDetails keys: {list(send_details.keys())}", file=sys.stderr)
            sent = extract_stat(send_details,
                "sendCount", "emailsSent", "sent", "totalSent",
                "contactedCount", "messagesCount",
            )
            if sent > 0:
                print(f"  ✓ Stats from sendDetails", file=sys.stderr)
                return {
                    "sent":         sent,
                    "opened":       extract_stat(send_details, "openCount",       "emailsOpened",       "opened"),
                    "clicked":      extract_stat(send_details, "clickCount",       "emailsClicked",      "clicked"),
                    "replied":      extract_stat(send_details, "replyCount",       "emailsReplied",      "replied"),
                    "bounced":      extract_stat(send_details, "bounceCount",      "emailsBounced",      "bounced"),
                    "unsubscribed": extract_stat(send_details, "unsubscribeCount", "emailsUnsubscribed", "unsubscribed"),
                }
    except Exception as e:
        print(f"  ! sendDetails lookup failed: {e}", file=sys.stderr)

    print(f"  ! Could not find stats for '{campaign_name}' — all endpoints returned zeros", file=sys.stderr)
    return zero


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

    all_names = [c.get("name", c.get("_id")) for c in campaigns]
    print(f"  ✓ Found {len(campaigns)} total campaigns", file=sys.stderr)

    ih_campaigns = [
        c for c in campaigns
        if CAMPAIGN_FILTER.lower() in c.get("name", "").lower()
    ]

    if not ih_campaigns:
        print(f"  ! No campaigns matching '{CAMPAIGN_FILTER}'", file=sys.stderr)
        print(f"  ! Available: {all_names}", file=sys.stderr)

    # Check if the list response itself has stat fields on the first IH campaign
    if ih_campaigns:
        sample = ih_campaigns[0]
        print(f"  DEBUG campaign list object keys: {list(sample.keys())}", file=sys.stderr)

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

        # First check if stats are already in the list response
        sent_from_list = extract_stat(c,
            "sendCount", "emailsSent", "sent", "contactedCount",
            "totalSent", "messagesCount",
        )

        if sent_from_list > 0:
            print(f"  ✓ Stats from campaign list for '{name}'", file=sys.stderr)
            stats = {
                "sent":         sent_from_list,
                "opened":       extract_stat(c, "openCount",       "emailsOpened",       "opened"),
                "clicked":      extract_stat(c, "clickCount",       "emailsClicked",      "clicked"),
                "replied":      extract_stat(c, "replyCount",       "emailsReplied",      "replied"),
                "bounced":      extract_stat(c, "bounceCount",      "emailsBounced",      "bounced"),
                "unsubscribed": extract_stat(c, "unsubscribeCount", "emailsUnsubscribed", "unsubscribed"),
            }
        else:
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
        print(f"  ✓ '{name}': sent={stats['sent']}, opened={stats['opened']}, clicked={stats['clicked']}, replied={stats['replied']}", file=sys.stderr)

    # ── Step 3: compute aggregate rates
    total_sent   = totals["sent"]   or 1
    total_opened = totals["opened"] or 1

    totals["open_rate"]  = round((totals["opened"]  / total_sent)   * 100, 1)
    totals["ctr"]        = round((totals["clicked"] / total_opened) * 100, 1)
    totals["reply_rate"] = round((totals["replied"] / total_sent)   * 100, 1)

    if totals["sent"] == 0:
        totals["open_rate"] = totals["ctr"] = totals["reply_rate"] = 0

    print(f"  ✓ Totals: sent={totals['sent']}, open_rate={totals['open_rate']}%, "
          f"ctr={totals['ctr']}%, replies={totals['replied']}", file=sys.stderr)

    print(json.dumps(totals, indent=2))


if __name__ == "__main__":
    main()
