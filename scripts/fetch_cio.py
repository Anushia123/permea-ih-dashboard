"""
Fetch Customer.io campaign email metrics for the Insight Hub dashboard.

The campaign-level /campaigns/{id}/metrics endpoint returns zeros for journey
campaigns. Correct approach: fetch campaign details to get email action IDs,
then sum metrics across all email actions per campaign.

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

# Email action IDs per campaign — extracted from CIO Fly API (MCP query 2026-04-13).
# Only email-type actions; delays, branches, in-app excluded.
# Update if new email actions are added to a journey.
CAMPAIGN_EMAIL_ACTIONS = {
    "pta":          [638, 644, 645, 649, 650, 655, 656, 693],
    "core_journey": [665, 666, 670, 673, 677, 679, 686, 690, 691, 729],
    "urgency_journey": [],  # populate once urgency journey has email actions
}


def to_int(val):
    """Normalise CIO metric values — may be a scalar or a time-series list."""
    if isinstance(val, list):
        return sum(v for v in val if isinstance(v, (int, float)))
    return int(val) if val else 0


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


def fetch_action_metrics(campaign_id, action_id):
    """Fetch email delivery metrics for a single campaign action."""
    resp = requests.get(
        f"{API_BASE}/campaigns/{campaign_id}/actions/{action_id}/metrics",
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_campaign_email_metrics(campaign, ctype):
    """
    Sum email metrics across all email actions in a campaign.
    Returns a dict, or None if the campaign has no email actions or all calls fail.
    """
    cid  = campaign["id"]
    name = campaign.get("name", f"Campaign {cid}")

    try:
        action_ids = CAMPAIGN_EMAIL_ACTIONS.get(ctype, [])
        if not action_ids:
            print(f"  ! CIO: no email action IDs configured for '{name}' ({ctype})", file=sys.stderr)
            return None

        print(f"  ✓ CIO: '{name}' — {len(action_ids)} email actions", file=sys.stderr)

        totals = {"sent": 0, "opened": 0, "clicked": 0, "bounced": 0, "unsubscribed": 0}

        for aid in action_ids:
            try:
                data = fetch_action_metrics(cid, aid)
                m    = data.get("metric", {})
                delivered = to_int(m.get("delivered", 0))
                bounced   = to_int(m.get("bounced",   0))
                totals["sent"]         += delivered + bounced
                totals["opened"]       += to_int(m.get("opened",       0))
                totals["clicked"]      += to_int(m.get("clicked",      0))
                totals["bounced"]      += bounced
                totals["unsubscribed"] += to_int(m.get("unsubscribed", 0))
            except Exception as e:
                print(f"    ! action {aid} error: {e}", file=sys.stderr)

        open_rate = round((totals["opened"]  / max(totals["sent"],   1)) * 100, 1)
        ctr       = round((totals["clicked"] / max(totals["opened"], 1)) * 100, 1)

        print(f"  ✓ CIO: '{name}' totals — sent={totals['sent']}, open={open_rate}%, ctr={ctr}%", file=sys.stderr)

        return {
            "name":         name,
            "sent":         totals["sent"],
            "opened":       totals["opened"],
            "clicked":      totals["clicked"],
            "bounced":      totals["bounced"],
            "unsubscribed": totals["unsubscribed"],
            "open_rate":    open_rate,
            "ctr":          ctr,
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
            campaigns_by_type[ctype] = get_campaign_email_metrics(campaign, ctype)
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
