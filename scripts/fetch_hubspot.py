"""
Fetch HubSpot CRM data for the Insight Hub Free Trial dashboard.

Requires env var: HUBSPOT_TOKEN (Private App access token, pat-eu1-... prefix)

Fetches:
  - IH Free Trial deals from the general pipeline (filtered by deal name)
  - Pipeline stages for closed-won detection (probability == 1.0)
  - Contact list member count for the IH sequence (crm.lists.read)
  - Landing page visits via Analytics API v2 (requires content scope)

Gate 1 HubSpot email stats (sequence) are NOT available via API.
They come from data/manual_overrides.json instead.
"""

import os
import json
import sys
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

MANUAL_OVERRIDES_PATH = Path(__file__).parent.parent / "data" / "manual_overrides.json"


def load_manual_overrides():
    if MANUAL_OVERRIDES_PATH.exists():
        return json.loads(MANUAL_OVERRIDES_PATH.read_text())
    return {}

API_BASE = "https://api.hubapi.com"

api_key = os.environ.get("HUBSPOT_TOKEN")
if not api_key:
    print("✗ HUBSPOT_TOKEN not set — exiting", file=sys.stderr)
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
}

# Deals in the general pipeline are identified by name.
# Commercial team must include this string in every IH Free Trial deal name.
DEAL_NAME_FILTER = "Insight Hub Free Trial"

# All IH deals live in the default (general) pipeline.
PIPELINE_ID = "default"

# Name of the HubSpot contact list tracking sequence enrollment.
LIST_NAME = "Insight Hub Free Demo Access - Warm Outreach"

# Landing page path to track (HubSpot Analytics API matches on URL path)
LANDING_PAGE_PATH = "/permea/insighthub/freetrial"
CAMPAIGN_START = os.environ.get("CAMPAIGN_START", "2026-03-01")


def fetch_pipeline_stages(pipeline_id):
    """
    Fetch stage metadata for a pipeline.
    Returns {stage_id: {"label": str, "probability": float}}.

    NOTE: In this HubSpot portal the stage IDs "closedlost" / "closedwon"
    have their labels swapped. Always use probability, not stage ID or label:
      - probability == 1.0 → Closed Won
      - probability == 0.0 → Closed Lost
    """
    url = f"{API_BASE}/crm/v3/pipelines/deals/{pipeline_id}/stages"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    stages = resp.json().get("results", [])
    return {
        s["id"]: {
            "label":       s.get("label", s["id"]),
            "probability": float(s.get("metadata", {}).get("probability", -1)),
        }
        for s in stages
    }


def fetch_deals():
    """
    Fetch all IH Free Trial deals using a name-contains filter.
    No pipeline ID or dedicated pipeline needed — works on the general pipeline.
    """
    url = f"{API_BASE}/crm/v3/objects/deals/search"
    payload = {
        "filterGroups": [{
            "filters": [{
                "propertyName": "dealname",
                "operator":     "CONTAINS_TOKEN",
                "value":        DEAL_NAME_FILTER,
            }]
        }],
        "properties": ["dealname", "dealstage", "amount", "createdate", "closedate"],
        "limit": 200,
    }
    resp = requests.post(url, headers=HEADERS, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json().get("results", [])


def fetch_list_member_count():
    """
    Fetch member count for the IH sequence contact list.
    Returns int if found, None if list not found or API unavailable.
    """
    url = f"{API_BASE}/crm/v3/lists/"
    params = {"limit": 100}
    resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    lists = resp.json().get("lists", [])
    for lst in lists:
        if LIST_NAME.lower() in lst.get("name", "").lower():
            return lst.get("memberCount", 0)
    return None


def fetch_landing_page_visits():
    """
    Fetch total visit count for the IH landing page via HubSpot Analytics API v2.
    Requires 'content' scope on the Private App token.
    Returns int (visit count) or None if unavailable.
    """
    try:
        start = datetime.strptime(CAMPAIGN_START, "%Y-%m-%d").strftime("%Y%m%d")
        end   = datetime.now(timezone.utc).strftime("%Y%m%d")
        url   = f"{API_BASE}/analytics/v2/reports/pages/total"
        params = {"start": start, "end": end, "limit": 500}
        resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        breakdowns = data.get("breakdowns", [])
        print(f"  ✓ Analytics API: {len(breakdowns)} pages returned", file=sys.stderr)
        for page in breakdowns:
            slug = page.get("breakdown", "")
            if LANDING_PAGE_PATH in slug:
                visits = page.get("sessions", page.get("pageviews", page.get("visits", 0)))
                print(f"  ✓ Landing page '{slug}': {visits} sessions", file=sys.stderr)
                return visits
        print(f"  ! Landing page '{LANDING_PAGE_PATH}' not found in results — checking available pages:", file=sys.stderr)
        for page in breakdowns[:5]:
            print(f"    - {page.get('breakdown')} : {page.get('sessions', page.get('pageviews'))}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  ✗ Landing page analytics error: {e}", file=sys.stderr)
        return None


def aggregate_deals(deals, stage_map):
    """
    Count deals by stage. Detect closed won/lost via probability, not stage name.
    """
    by_stage   = {}
    closed_won  = 0
    closed_lost = 0
    deals_detail = []

    for deal in deals:
        props    = deal.get("properties", {})
        stage_id = props.get("dealstage", "unknown")
        stage    = stage_map.get(stage_id, {"label": stage_id, "probability": -1})
        label    = stage["label"]
        prob     = stage["probability"]

        by_stage[label] = by_stage.get(label, 0) + 1

        if prob == 1.0:
            closed_won += 1
        elif prob == 0.0:
            closed_lost += 1

        deals_detail.append({
            "name":   props.get("dealname"),
            "stage":  label,
            "amount": props.get("amount"),
        })

    return {
        "deals_created":   len(deals),
        "deals_closed_h1": closed_won,   # field name matches build_metrics.py
        "deals_closed_lost": closed_lost,
        "deals_by_stage":  by_stage,
        "deals":           deals_detail,
    }


def main():
    print("→ Fetching HubSpot metrics…", file=sys.stderr)
    result = {
        "source":     "hubspot",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

    # Pipeline stages (needed for closed-won detection)
    try:
        stage_map = fetch_pipeline_stages(PIPELINE_ID)
        print(f"  ✓ Pipeline stages fetched: {len(stage_map)} stages", file=sys.stderr)
    except Exception as e:
        print(f"  ✗ Pipeline stages error: {e}", file=sys.stderr)
        stage_map = {}

    # IH Free Trial deals
    try:
        deals = fetch_deals()
        print(f"  ✓ IH Free Trial deals found: {len(deals)}", file=sys.stderr)
        result.update(aggregate_deals(deals, stage_map))
    except Exception as e:
        print(f"  ✗ Deals fetch error: {e}", file=sys.stderr)
        result.update({
            "deals_created":    0,
            "deals_closed_h1":  0,
            "deals_closed_lost": 0,
            "deals_by_stage":   {},
            "deals":            [],
        })

    # Contact list member count (sequence enrollment)
    # Prefer manual_overrides.json — API returns list membership count which differs from
    # actual sequence enrollments. Manual value (from HubSpot Sequences > Performance tab) is more accurate.
    overrides = load_manual_overrides()
    sequence_override = overrides.get("hubspot_sequence", {})
    manual_enrolled = sequence_override.get("enrolled")
    if manual_enrolled is not None:
        result["sequence_enrolled"] = manual_enrolled
        print(f"  ✓ Sequence enrolled (manual override): {manual_enrolled}", file=sys.stderr)
    else:
        try:
            count = fetch_list_member_count()
            result["sequence_enrolled"] = count
            print(f"  ✓ Sequence enrolled (API fallback): {count}", file=sys.stderr)
        except Exception as e:
            result["sequence_enrolled"] = None
            print(f"  ✗ Enrolled fetch error: {e}", file=sys.stderr)

    # Sequence stats (open rate, reply rate) — always from manual_overrides.json
    # HubSpot Sequences API has no statistics endpoints.
    result["sequence_stats"] = {
        "emails_sent": sequence_override.get("emails_sent", 0),
        "open_rate":   sequence_override.get("open_rate",   0.0),
        "click_rate":  sequence_override.get("click_rate",  0.0),
        "reply_rate":  sequence_override.get("reply_rate",  0.0),
        "last_updated": sequence_override.get("last_updated"),
    }
    print(f"  ✓ Sequence stats from manual overrides (updated: {sequence_override.get('last_updated')})", file=sys.stderr)

    # Landing page visits (requires content scope)
    result["landing_page_visits"] = fetch_landing_page_visits()

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
