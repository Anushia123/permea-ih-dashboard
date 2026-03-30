"""
Fetch PostHog event data for the Insight Hub dashboard.

Requires env var: POSTHOG_API_KEY (Project API key from PostHog settings)
Requires env var: POSTHOG_PROJECT_ID (numeric project ID from PostHog settings)
Optional env vars (override event names if different in your PostHog setup):
  POSTHOG_EVENT_ACCOUNT_CREATED   (default: account_created)
  POSTHOG_EVENT_LOGIN             (default: user_logged_in)
  POSTHOG_EVENT_WIDGET_CLICK      (default: widget_clicked)
  POSTHOG_EVENT_SEGMENT_SUBMIT    (default: segment_submitted)
  POSTHOG_EVENT_CTA_CLICK         (default: cta_clicked_commercial)

⚠ IMPORTANT: Confirm these event names with the product team before running.
The product team must confirm which events are actually being tracked in PostHog.
"""

import os
import json
import sys
import requests
from datetime import datetime, timezone, timedelta

API_BASE   = os.environ.get("POSTHOG_HOST", "https://eu.posthog.com")  # change to app.posthog.com if on US cloud
PROJECT_ID = os.environ["POSTHOG_PROJECT_ID"]
HEADERS = {
    "Authorization": f"Bearer {os.environ['POSTHOG_API_KEY']}",
    "Content-Type": "application/json",
}

# Event names — override with env vars if your product uses different names
EVENT_ACCOUNT_CREATED = os.environ.get("POSTHOG_EVENT_ACCOUNT_CREATED", "account_created")
EVENT_LOGIN           = os.environ.get("POSTHOG_EVENT_LOGIN",           "user_logged_in")
EVENT_WIDGET_CLICK    = os.environ.get("POSTHOG_EVENT_WIDGET_CLICK",    "widget_clicked")
EVENT_SEGMENT_SUBMIT  = os.environ.get("POSTHOG_EVENT_SEGMENT_SUBMIT",  "segment_submitted")
EVENT_CTA_CLICK       = os.environ.get("POSTHOG_EVENT_CTA_CLICK",       "cta_clicked_commercial")

# Campaign window — how far back to look
DAYS_LOOKBACK = int(os.environ.get("POSTHOG_DAYS_LOOKBACK", "90"))
DATE_FROM = (datetime.now(timezone.utc) - timedelta(days=DAYS_LOOKBACK)).strftime("%Y-%m-%d")
DATE_TO   = datetime.now(timezone.utc).strftime("%Y-%m-%d")


def query_event_count(event_name, filters=None):
    """
    Use the PostHog Insights API to count unique users who fired an event.
    Returns count of unique users.
    """
    url = f"{API_BASE}/api/projects/{PROJECT_ID}/insights/trend/"
    payload = {
        "events": [{"id": event_name, "type": "events", "math": "dau"}],
        "date_from": DATE_FROM,
        "date_to": DATE_TO,
        "display": "ActionsLineGraph",
        "interval": "day",
    }
    if filters:
        payload["properties"] = filters

    resp = requests.post(url, headers=HEADERS, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    # Sum all daily values to get total unique users over the period
    results = data.get("result", [])
    if not results:
        return 0
    total = sum(results[0].get("data", []))
    return total


def query_funnel(events):
    """
    Run a funnel query through the specified event sequence.
    Returns conversion counts per step.
    """
    url = f"{API_BASE}/api/projects/{PROJECT_ID}/insights/funnel/"
    payload = {
        "events": [{"id": e, "type": "events", "order": i} for i, e in enumerate(events)],
        "date_from": DATE_FROM,
        "date_to": DATE_TO,
        "funnel_window_interval": 7,
        "funnel_window_interval_unit": "day",
    }
    resp = requests.post(url, headers=HEADERS, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("result", [])
    return [step.get("count", 0) for step in results]


def query_users_active_within_48h(total_signups):
    """
    Count users who fired login_event within 48h of account_created.
    Uses a simpler approach: count logins in the first 2 days per user.
    This is an approximation — exact cohort analysis needs PostHog SQL.
    """
    # For now, use a 48h funnel as a proxy
    # PostHog funnel with 2-day window
    url = f"{API_BASE}/api/projects/{PROJECT_ID}/insights/funnel/"
    payload = {
        "events": [
            {"id": EVENT_ACCOUNT_CREATED, "type": "events", "order": 0},
            {"id": EVENT_LOGIN,           "type": "events", "order": 1},
        ],
        "date_from": DATE_FROM,
        "date_to": DATE_TO,
        "funnel_window_interval": 2,
        "funnel_window_interval_unit": "day",
    }
    resp = requests.post(url, headers=HEADERS, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("result", [])
    if len(results) >= 2:
        return results[1].get("count", 0)
    return 0


def main():
    print("→ Fetching PostHog metrics…", file=sys.stderr)
    result = {
        "source": "posthog",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "date_range": {"from": DATE_FROM, "to": DATE_TO},
    }

    # Funnel: account_created → widget_clicked → segment_submitted → cta_clicked
    try:
        funnel_counts = query_funnel([
            EVENT_ACCOUNT_CREATED,
            EVENT_WIDGET_CLICK,
            EVENT_SEGMENT_SUBMIT,
            EVENT_CTA_CLICK,
        ])
        print(f"  ✓ PostHog funnel: {funnel_counts}", file=sys.stderr)

        verified_signups  = funnel_counts[0] if len(funnel_counts) > 0 else 0
        activated_users   = funnel_counts[1] if len(funnel_counts) > 1 else 0
        segment_submitted = funnel_counts[2] if len(funnel_counts) > 2 else 0
        cta_clicks        = funnel_counts[3] if len(funnel_counts) > 3 else 0

        result["verified_signups"]        = verified_signups
        result["activated_users"]         = activated_users
        result["segment_submissions"]     = segment_submitted
        result["cta_clicks_inapp"]        = cta_clicks
        result["activation_rate_7day"]    = round((activated_users / max(verified_signups, 1)) * 100, 1)
        result["submission_rate_signup"]  = round((segment_submitted / max(verified_signups, 1)) * 100, 1)
        result["submission_rate_activation"] = round((segment_submitted / max(activated_users, 1)) * 100, 1)
        result["commercial_touch_rate"]   = round((cta_clicks / max(segment_submitted, 1)) * 100, 1)

    except Exception as e:
        print(f"  ✗ PostHog funnel error: {e}", file=sys.stderr)
        print(f"    Check that event names are correct: {EVENT_ACCOUNT_CREATED}, {EVENT_WIDGET_CLICK}, {EVENT_SEGMENT_SUBMIT}", file=sys.stderr)
        result.update({
            "verified_signups": 0, "activated_users": 0,
            "segment_submissions": 0, "cta_clicks_inapp": 0,
            "activation_rate_7day": 0, "submission_rate_signup": 0,
            "submission_rate_activation": 0, "commercial_touch_rate": 0,
        })

    # Login within 48h
    try:
        login_48h = query_users_active_within_48h(result.get("verified_signups", 0))
        result["logged_in_within_48h"] = login_48h
        result["login_48h_rate"] = round(
            (login_48h / max(result.get("verified_signups", 1), 1)) * 100, 1
        )
        print(f"  ✓ PostHog 48h login rate: {result['login_48h_rate']}%", file=sys.stderr)
    except Exception as e:
        print(f"  ✗ PostHog 48h login error: {e}", file=sys.stderr)
        result["logged_in_within_48h"] = 0
        result["login_48h_rate"] = 0

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
