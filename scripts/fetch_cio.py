"""
Fetch Customer.io campaign email metrics for the Insight Hub dashboard.

Returns per-campaign metrics keyed by journey type:
  - pta:             PTA journey (drives segment submission — Gate 4)
  - core_journey:    Core Journey (drives conversion — Gate 5)
  - urgency_journey: Urgency Journey (last-days conversion push — Gate 5)

Requires env var: CIO_API_KEY (App API key from CIO Account Settings → API Credentials)
Optional env var: CIO_CAMPAIGN_NAME (default: "Insight Hub")
"""

import os
import json
import sys
import requests
from datetime import datetime, timezone

# EU region workspace — must use api-eu.customer.io, not api.customer.io
API_BASE = "https://api-eu.customer.io/v1"

api_key = os.environ.get("CIO_API_KEY")
if not api_key:
    print("✗ CIO_API_KEY not set — exiting", file=sys.stderr)
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type":  "application/json",
}

CAMPAIGN_IDENTIFIER = os.environ.get("CIO_CAMPAIGN_NAME", "Insight Hub")


def classify_campaign(name):
    """
    Identify which journey a campaign belongs to by its name.
    Returns: 'pta', 'core_journey', 'urgency_journey', or None.
    """
    n = name.lower()
    if "urgency" in n:
        return "urgency_journey"
    if "core journey" in n:
        return "core_journey"
    if "pta" in n:
        return "pta"
    return None


def fetch_all_campaigns():
    resp = requests.get(f"{API_BASE}/campaigns", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json().get("campaigns", [])


def fetch_campaign_metrics(campaign_id):
    resp = requests.get(
        f"{API_BASE}/campaigns/{campaign_id}/metrics",
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_campaign_email_metrics(campaign):
    """
    Fetch and return structured email metrics for a single campaign.
    Returns a dict, or None if the API call fails.
    """
    cid  = campaign["id"]
    name = campaign.get("name", f"Campaign {cid}")
    try:
        data = fetch_campaign_metrics(cid)
        m    = data.get("metric", {})
        delivered  = m.get("delivered",    0)
        bounced    = m.get("bounced",      0)
        sent       = delivered + bounced
        opened     = m.get("opened",       0)
        clicked    = m.get("clicked",      0)
        open_rate  = round((opened  / max(sent,   1)) * 100, 1)
        ctr        = round((clicked / max(opened, 1)) * 100, 1)
        print(f"  ✓ CIO: '{name}' — sent={sent}, open={open_rate}%, ctr={ctr}%", file=sys.stderr)
        return {
            "name":        name,
            "sent":        sent,
            "opened":      opened,
            "clicked":     clicked,
            "bounced":     bounced,
            "unsubscribed":m.get("unsubscribed", 0),
            "open_rate":   open_rate,
            "ctr":         ctr,
        }
    except Exception as e:
        print(f"  ✗ CIO: could not fetch '{name}' (id={cid}): {e}", file=sys.stderr)
        return None


def main():
    print("→ Fetching Customer.io metrics…", file=sys.stderr)

    all_campaigns = fetch_all_campaigns()
    ih_campaigns  = [c for c in all_campaigns if CAMPAIGN_IDENTIFIER.lower() in c.get("name", "").lower()]

    if not ih_campaigns:
        print(f"  ! No CIO campaigns matching '{CAMPAIGN_IDENTIFIER}' — available: {[c.get('name') for c in all_campaigns[:10]]}", file=sys.stderr)

    campaigns_by_type = {"pta": None, "core_journey": None, "urgency_journey": None}

    for campaign in ih_campaigns:
        ctype = classify_campaign(campaign.get("name", ""))
        if ctype:
            campaigns_by_type[ctype] = get_campaign_email_metrics(campaign)
        else:
            print(f"  ! CIO: unclassified campaign '{campaign.get('name')}' — skipping", file=sys.stderr)

    result = {
        "source":     "customer.io",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "campaigns":  campaigns_by_type,
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
