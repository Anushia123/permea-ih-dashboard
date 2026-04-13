"""
Fetch Customer.io campaign email metrics for the Insight Hub dashboard.

Fetches two things:
  1. Email delivery/engagement metrics across all Insight Hub campaigns
  2. segment_submitted event count from CIO journey data (primary source per system architecture)

Requires env var: CIO_API_KEY (Reporting API key from CIO workspace settings)
Optional env var: CIO_CAMPAIGN_NAME (default: "Insight Hub")
Optional env var: CIO_SEGMENT_EVENT (default: "segment_submitted")
"""

import os
import json
import sys
import requests
from datetime import datetime, timezone

# EU region workspace — must use api-eu.customer.io, not api.customer.io
# Using the wrong region causes 401 errors even with a valid key.
API_BASE = "https://api-eu.customer.io/v1"

api_key = os.environ.get("CIO_API_KEY")
if not api_key:
    print("✗ CIO_API_KEY not set — exiting", file=sys.stderr)
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
}

CAMPAIGN_IDENTIFIER = os.environ.get("CIO_CAMPAIGN_NAME", "Insight Hub")
SEGMENT_EVENT_NAME  = os.environ.get("CIO_SEGMENT_EVENT", "segment_submitted")


def fetch_all_campaigns():
    """Get a list of all campaigns/broadcasts in the workspace."""
    resp = requests.get(f"{API_BASE}/campaigns", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json().get("campaigns", [])


def fetch_campaign_metrics(campaign_id):
    """Get email delivery/engagement metrics for a specific campaign."""
    resp = requests.get(
        f"{API_BASE}/campaigns/{campaign_id}/metrics",
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_segment_submissions():
    """
    Fetch count of unique customers who triggered the segment_submitted event in CIO.
    Uses the CIO Reporting API /v1/metrics/events endpoint.
    Returns an integer count, or None if the API call fails.
    """
    try:
        resp = requests.get(
            f"{API_BASE}/metrics/events",
            headers=HEADERS,
            params={"name": SEGMENT_EVENT_NAME, "period": "days", "steps": 90},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        # Sum unique counts across all time buckets returned
        metric = data.get("metric", {})
        unique_counts = metric.get("unique_counts", metric.get("counts", []))
        total = sum(unique_counts) if unique_counts else None
        print(f"  ✓ CIO: segment_submitted event count = {total}", file=sys.stderr)
        return total
    except Exception as e:
        print(f"  ! CIO: could not fetch segment_submitted event ({e}) — PostHog will be used as fallback", file=sys.stderr)
        return None


def find_ih_campaigns(campaigns):
    """Filter campaigns to those related to Insight Hub."""
    return [
        c for c in campaigns
        if CAMPAIGN_IDENTIFIER.lower() in c.get("name", "").lower()
    ]


def aggregate_metrics(campaign_list):
    """
    Aggregate email metrics across all IH campaigns.
    Returns a dict with: sent, opened, open_rate, clicked, ctr, bounced, unsubscribed.
    """
    totals = {
        "sent": 0,
        "opened": 0,
        "clicked": 0,
        "bounced": 0,
        "unsubscribed": 0,
        "campaigns_found": [],
    }

    for campaign in campaign_list:
        cid = campaign["id"]
        name = campaign.get("name", f"Campaign {cid}")
        try:
            metrics = fetch_campaign_metrics(cid)
            m = metrics.get("metric", {})
            totals["sent"]          += m.get("delivered", 0) + m.get("bounced", 0)
            totals["opened"]        += m.get("opened", 0)
            totals["clicked"]       += m.get("clicked", 0)
            totals["bounced"]       += m.get("bounced", 0)
            totals["unsubscribed"]  += m.get("unsubscribed", 0)
            totals["campaigns_found"].append({"id": cid, "name": name})
            print(f"  ✓ CIO: fetched '{name}' (id={cid})", file=sys.stderr)
        except Exception as e:
            print(f"  ✗ CIO: could not fetch '{name}': {e}", file=sys.stderr)

    sent = totals["sent"] or 1  # avoid div/0
    totals["open_rate"] = round((totals["opened"] / sent) * 100, 1)
    totals["ctr"]       = round((totals["clicked"] / max(totals["opened"], 1)) * 100, 1)

    return totals


def main():
    print("→ Fetching Customer.io metrics…", file=sys.stderr)
    campaigns = fetch_all_campaigns()
    ih_campaigns = find_ih_campaigns(campaigns)

    if not ih_campaigns:
        print(f"  ! No CIO campaigns found matching '{CAMPAIGN_IDENTIFIER}'", file=sys.stderr)
        print(f"  ! Available: {[c.get('name') for c in campaigns[:10]]}", file=sys.stderr)

    metrics = aggregate_metrics(ih_campaigns)

    # Segment submissions — CIO is primary source per system architecture
    segment_count = fetch_segment_submissions()
    metrics["segment_submissions"] = segment_count  # None = no data; build_metrics falls back to PostHog

    metrics["fetched_at"] = datetime.now(timezone.utc).isoformat()
    metrics["source"] = "customer.io"

    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
