"""
Fetch PostHog event data for the Insight Hub dashboard.

Uses PostHog's HogQL query API (/api/projects/{id}/query/) — more reliable
than the legacy /insights/ endpoints and only requires `query:read` scope.

Requires env var: POSTHOG_API_KEY (Personal API key from PostHog settings)
Optional env vars:
  POSTHOG_PROJECT_ID  (default: 9143, EU cloud)
  POSTHOG_DAYS_LOOKBACK (default: 90)
  POSTHOG_HOST        (default: https://eu.posthog.com)

Event names (override via env vars if needed):
  POSTHOG_EVENT_ACCOUNT_CREATED   (default: account_created)
  POSTHOG_EVENT_LOGIN             (default: user_logged_in — pending confirmation)
  POSTHOG_EVENT_ACTIVATION        (default: widget_used)
  POSTHOG_EVENT_SEGMENT_SUBMIT    (default: personalized_project_review_sent_request)

CTA events (hardcoded — two events summed):
  free_trial_talk_to_expert_clicked + free_trial_contact_us_clicked

All queries filter to plan='free' to exclude paid/internal users.
"""

import os
import json
import sys
import requests
from datetime import datetime, timezone, timedelta

API_BASE   = os.environ.get("POSTHOG_HOST", "https://eu.posthog.com")
PROJECT_ID = os.environ.get("POSTHOG_PROJECT_ID", "9143")

api_key = os.environ.get("POSTHOG_API_KEY")
if not api_key:
    print("✗ POSTHOG_API_KEY environment variable is not set", file=sys.stderr)
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
}

# Confirmed event names from product team (March 2026)
EVENT_ACCOUNT_CREATED = os.environ.get("POSTHOG_EVENT_ACCOUNT_CREATED", "account_created")
EVENT_LOGIN           = os.environ.get("POSTHOG_EVENT_LOGIN",           "user_logged_in")  # pending confirmation
EVENT_ACTIVATION      = os.environ.get("POSTHOG_EVENT_ACTIVATION",      "widget_used")
EVENT_SEGMENT_SUBMIT  = os.environ.get("POSTHOG_EVENT_SEGMENT_SUBMIT",  "personalized_project_review_sent_request")
EVENT_CTA_TALK        = "free_trial_talk_to_expert_clicked"
EVENT_CTA_CONTACT     = "free_trial_contact_us_clicked"

# Exclusion filters (matching product team dashboard logic)
# - catchmail: fake test accounts
# - temedica.com: internal team accounts
EXCLUDE_CATCHMAIL = "catchmail"
EXCLUDE_DOMAIN    = "temedica.com"

# Campaign window
DAYS_LOOKBACK = int(os.environ.get("POSTHOG_DAYS_LOOKBACK", "90"))
DATE_FROM = (datetime.now(timezone.utc) - timedelta(days=DAYS_LOOKBACK)).strftime("%Y-%m-%d")
DATE_TO   = datetime.now(timezone.utc).strftime("%Y-%m-%d")

QUERY_URL = f"{API_BASE}/api/projects/{PROJECT_ID}/query/"


def hogql(sql):
    """
    Run a HogQL query against the PostHog query API.
    Returns the full response dict.
    Raises on HTTP errors.
    """
    resp = requests.post(
        QUERY_URL,
        headers=HEADERS,
        json={"query": {"kind": "HogQLQuery", "query": sql}},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def base_filters():
    """Return the standard WHERE clause filters used across all queries."""
    return f"""
          AND properties.plan = 'free'
          AND properties.email NOT ILIKE '%{EXCLUDE_CATCHMAIL}%'
          AND properties.email NOT ILIKE '%{EXCLUDE_DOMAIN}%'
    """


def count_unique(event_name, extra_where=""):
    """Count distinct persons who fired an event, excluding internal/test accounts."""
    sql = f"""
        SELECT count(distinct person_id)
        FROM events
        WHERE event = '{event_name}'
          {base_filters()}
          AND timestamp >= toDateTime('{DATE_FROM}')
          AND timestamp <= toDateTime('{DATE_TO}')
          {extra_where}
    """
    data = hogql(sql)
    rows = data.get("results", [[0]])
    return int(rows[0][0]) if rows else 0


def count_funnel_steps(events):
    """
    Sequential funnel: each step counts only users who were also in the base (signup) cohort.
    Guarantees signups >= activated >= market_defs.
    """
    base_event = events[0]
    counts = [count_unique(base_event)]

    for event in events[1:]:
        sql = f"""
            SELECT count(distinct person_id)
            FROM events
            WHERE event = '{event}'
              {base_filters()}
              AND timestamp >= toDateTime('{DATE_FROM}')
              AND timestamp <= toDateTime('{DATE_TO}')
              AND person_id IN (
                  SELECT distinct person_id
                  FROM events
                  WHERE event = '{base_event}'
                    {base_filters()}
                    AND timestamp >= toDateTime('{DATE_FROM}')
                    AND timestamp <= toDateTime('{DATE_TO}')
              )
        """
        data = hogql(sql)
        rows = data.get("results", [[0]])
        counts.append(int(rows[0][0]) if rows else 0)

    return counts


def count_funnel_48h(event_a, event_b):
    """
    Count users who fired event_b within 48h of event_a (plan=free).
    Uses a correlated subquery approach in HogQL.
    """
    sql = f"""
        SELECT count(distinct e2.person_id)
        FROM events e1
        JOIN events e2 ON e1.person_id = e2.person_id
        WHERE e1.event = '{event_a}'
          AND e2.event = '{event_b}'
          AND e1.properties.plan = 'free'
          AND e1.properties.email NOT ILIKE '%{EXCLUDE_CATCHMAIL}%'
          AND e1.properties.email NOT ILIKE '%{EXCLUDE_DOMAIN}%'
          AND e2.timestamp >= e1.timestamp
          AND e2.timestamp <= e1.timestamp + INTERVAL 2 DAY
          AND e1.timestamp >= toDateTime('{DATE_FROM}')
          AND e1.timestamp <= toDateTime('{DATE_TO}')
    """
    data = hogql(sql)
    rows = data.get("results", [[0]])
    return int(rows[0][0]) if rows else 0


def count_by_utm_source(event_name):
    """
    Break down event counts by utm_source for ih_free_trial campaign (plan=free).
    Returns dict of {utm_source: count}.
    """
    sql = f"""
        SELECT
            properties.utm_source AS utm_source,
            count(distinct person_id) AS cnt
        FROM events
        WHERE event = '{event_name}'
          {base_filters()}
          AND properties.utm_campaign = 'ih_free_trial'
          AND timestamp >= toDateTime('{DATE_FROM}')
          AND timestamp <= toDateTime('{DATE_TO}')
        GROUP BY utm_source
        ORDER BY cnt DESC
    """
    data = hogql(sql)
    rows = data.get("results", [])
    return {row[0]: int(row[1]) for row in rows if row[0]}


def main():
    print("→ Fetching PostHog metrics…", file=sys.stderr)
    print(f"  Project: {PROJECT_ID} | Range: {DATE_FROM} → {DATE_TO}", file=sys.stderr)

    result = {
        "source": "posthog",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "date_range": {"from": DATE_FROM, "to": DATE_TO},
    }

    # Gate 2/3/4 funnel: account_created → widget_used → market definition submitted
    try:
        funnel_counts = count_funnel_steps([
            EVENT_ACCOUNT_CREATED,
            EVENT_ACTIVATION,
            EVENT_SEGMENT_SUBMIT,
        ])
        verified_signups  = funnel_counts[0]
        activated_users   = funnel_counts[1]
        segment_submitted = funnel_counts[2]

        result["verified_signups"]           = verified_signups
        result["activated_users"]            = activated_users
        result["segment_submissions"]        = segment_submitted
        result["activation_rate_7day"]       = round((activated_users   / max(verified_signups, 1)) * 100, 1)
        result["submission_rate_signup"]     = round((segment_submitted / max(verified_signups, 1)) * 100, 1)
        result["submission_rate_activation"] = round((segment_submitted / max(activated_users,  1)) * 100, 1)
        print(f"  ✓ Funnel: {verified_signups} signups → {activated_users} activated → {segment_submitted} market defs", file=sys.stderr)

    except Exception as e:
        print(f"  ✗ Funnel error: {e}", file=sys.stderr)
        result.update({
            "verified_signups": 0, "activated_users": 0,
            "segment_submissions": 0, "activation_rate_7day": 0,
            "submission_rate_signup": 0, "submission_rate_activation": 0,
        })

    # Gate 5: CTA clicks (talk_to_expert + contact_us)
    try:
        talk    = count_unique(EVENT_CTA_TALK)
        contact = count_unique(EVENT_CTA_CONTACT)
        cta_clicks = talk + contact
        result["cta_clicks_inapp"]      = cta_clicks
        result["commercial_touch_rate"] = round((cta_clicks / max(result.get("segment_submissions", 1), 1)) * 100, 1)
        print(f"  ✓ CTA clicks: {cta_clicks} (talk={talk}, contact={contact})", file=sys.stderr)
    except Exception as e:
        print(f"  ✗ CTA clicks error: {e}", file=sys.stderr)
        result["cta_clicks_inapp"]      = 0
        result["commercial_touch_rate"] = 0

    # Gate 2: sign-ups by UTM source
    try:
        utm_breakdown = count_by_utm_source(EVENT_ACCOUNT_CREATED)
        result["signups_by_utm_source"] = utm_breakdown
        print(f"  ✓ UTM breakdown: {utm_breakdown}", file=sys.stderr)
    except Exception as e:
        print(f"  ✗ UTM breakdown error: {e}", file=sys.stderr)
        result["signups_by_utm_source"] = {}

    # Gate 3: login within 48h of signup
    try:
        login_48h = count_funnel_48h(EVENT_ACCOUNT_CREATED, EVENT_LOGIN)
        result["logged_in_within_48h"] = login_48h
        result["login_48h_rate"] = round(
            (login_48h / max(result.get("verified_signups", 1), 1)) * 100, 1
        )
        print(f"  ✓ 48h login: {login_48h} ({result['login_48h_rate']}%)", file=sys.stderr)
    except Exception as e:
        print(f"  ✗ 48h login error: {e}", file=sys.stderr)
        result["logged_in_within_48h"] = 0
        result["login_48h_rate"] = 0

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
