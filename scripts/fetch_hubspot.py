"""
Fetch HubSpot CRM data for the Insight Hub dashboard.

Requires env var: HUBSPOT_TOKEN (Private App access token)
Requires env var: HUBSPOT_PIPELINE_ID (the pipeline ID for this campaign)
  — find it in HubSpot > CRM > Deals > pipeline name > Settings > copy ID

Also fetches Tier 1 email metrics from HubSpot email sends.
"""

import os
import json
import sys
import requests
from datetime import datetime, timezone

API_BASE = "https://api.hubapi.com"
HEADERS = {
    "Authorization": f"Bearer {os.environ['HUBSPOT_TOKEN']}",
    "Content-Type": "application/json",
}

PIPELINE_ID = os.environ.get("HUBSPOT_PIPELINE_ID", "")
CAMPAIGN_NAME_FILTER = os.environ.get("HUBSPOT_CAMPAIGN_NAME", "Insight Hub")


def fetch_deals(pipeline_id):
    """
    Fetch all deals in the specified pipeline.
    Returns list of deals with stage, amount, createdate.
    """
    url = f"{API_BASE}/crm/v3/objects/deals/search"
    payload = {
        "filterGroups": [{
            "filters": [{
                "propertyName": "pipeline",
                "operator": "EQ",
                "value": pipeline_id
            }]
        }] if pipeline_id else [],
        "properties": ["dealname", "dealstage", "amount", "createdate", "closedate", "hubspot_owner_id"],
        "limit": 100,
    }
    resp = requests.post(url, headers=HEADERS, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json().get("results", [])


def fetch_pipeline_stages(pipeline_id):
    """Get stage names for a pipeline to map stage IDs → labels."""
    url = f"{API_BASE}/crm/v3/pipelines/deals/{pipeline_id}/stages"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    stages = resp.json().get("results", [])
    return {s["id"]: s.get("label", s["id"]) for s in stages}


def fetch_marketing_emails():
    """
    Fetch HubSpot marketing email stats (Tier 1 personal outreach).
    Returns open/click rates for emails matching CAMPAIGN_NAME_FILTER.
    """
    url = f"{API_BASE}/marketing/v3/emails"
    params = {"limit": 50, "state": "PUBLISHED"}
    resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    emails = resp.json().get("results", [])

    ih_emails = [
        e for e in emails
        if CAMPAIGN_NAME_FILTER.lower() in e.get("name", "").lower()
    ]

    totals = {"sent": 0, "opened": 0, "clicked": 0, "emails": []}
    for email in ih_emails:
        stats = email.get("stats", {})
        sent    = stats.get("sent", 0)
        opened  = stats.get("open", 0)
        clicked = stats.get("click", 0)
        totals["sent"]    += sent
        totals["opened"]  += opened
        totals["clicked"] += clicked
        totals["emails"].append({
            "name":      email.get("name"),
            "sent":      sent,
            "open_rate": round((opened / sent * 100), 1) if sent else 0,
            "ctr":       round((clicked / max(opened, 1) * 100), 1) if opened else 0,
        })
        print(f"  ✓ HubSpot email: '{email.get('name')}' (sent={sent})", file=sys.stderr)

    sent = totals["sent"] or 1
    totals["open_rate"] = round((totals["opened"] / sent) * 100, 1)
    totals["ctr"]       = round((totals["clicked"] / max(totals["opened"], 1)) * 100, 1)
    return totals


def aggregate_deals(deals, stage_map):
    """Count deals by stage, track follow-up metrics."""
    by_stage = {}
    deals_created = len(deals)
    closed_won = 0
    deals_detail = []

    for deal in deals:
        props    = deal.get("properties", {})
        stage_id = props.get("dealstage", "unknown")
        label    = stage_map.get(stage_id, stage_id)

        by_stage[label] = by_stage.get(label, 0) + 1
        if "closed_won" in stage_id.lower() or "won" in label.lower():
            closed_won += 1

        deals_detail.append({
            "name":  props.get("dealname"),
            "stage": label,
        })

    return {
        "deals_created": deals_created,
        "deals_closed_h1": closed_won,
        "deals_by_stage": by_stage,
        "deals": deals_detail,
    }


def main():
    print("→ Fetching HubSpot metrics…", file=sys.stderr)
    result = {
        "source": "hubspot",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

    # Pipeline / deals
    try:
        stage_map = fetch_pipeline_stages(PIPELINE_ID) if PIPELINE_ID else {}
        deals = fetch_deals(PIPELINE_ID)
        print(f"  ✓ HubSpot: {len(deals)} deals fetched", file=sys.stderr)
        result.update(aggregate_deals(deals, stage_map))
    except Exception as e:
        print(f"  ✗ HubSpot deals error: {e}", file=sys.stderr)
        result.update({"deals_created": 0, "deals_closed_h1": 0, "deals_by_stage": {}})

    # Email metrics (Tier 1)
    try:
        email_metrics = fetch_marketing_emails()
        result["email"] = email_metrics
    except Exception as e:
        print(f"  ✗ HubSpot email error: {e}", file=sys.stderr)
        result["email"] = {"sent": 0, "open_rate": 0, "ctr": 0}

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
