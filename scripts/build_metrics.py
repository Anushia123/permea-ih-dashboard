"""
Aggregates output from all fetch scripts into a single metrics.json file.

Usage:
  python build_metrics.py

This script is called by GitHub Actions after all fetch scripts have run.
Each fetch script writes its JSON output to a temp file in /tmp/ih_dash/.
This script reads those files and merges them into data/metrics.json.

The dashboard reads data/metrics.json directly.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

TEMP_DIR    = Path("/tmp/ih_dash")
OUTPUT_FILE = Path(__file__).parent.parent / "data" / "metrics.json"

# Load benchmarks — these are fixed and come from the build doc
BENCHMARKS = {
    "email_open_rate":       {"conservative": 25, "realistic": 30, "optimal": 35},
    "email_ctr":             {"conservative": 25, "realistic": 30, "optimal": 35},
    "account_creation_rate": {"conservative": 30, "realistic": 35, "optimal": 40},
    "activation_rate":       {"conservative": 60, "realistic": 65, "optimal": 75},
    "segment_submission_rate":{"conservative": 40, "realistic": 45, "optimal": 55},
    "sales_evaluation_rate": {"conservative": 55, "realistic": 60, "optimal": 70},
    "deal_close_rate":       {"conservative": 25, "realistic": 30, "optimal": 35},
    "deals_closed_h1":       {"conservative": 2,  "realistic": 4,  "optimal": 7},
    "landing_page_cvr":      {"conservative": 15, "realistic": 20, "optimal": 25},
}


def load_source(name):
    """Load JSON output from a fetch script's temp file."""
    path = TEMP_DIR / f"{name}.json"
    if not path.exists():
        print(f"  ! {name}.json not found — using empty data", file=sys.stderr)
        return {}
    try:
        with open(path) as f:
            content = f.read().strip()
        if not content:
            print(f"  ! {name}.json is empty — using empty data", file=sys.stderr)
            return {}
        return json.loads(content)
    except json.JSONDecodeError as e:
        print(f"  ! {name}.json is invalid JSON ({e}) — using empty data", file=sys.stderr)
        return {}


def determine_health(metrics):
    """
    Compute overall campaign health based on key gate metrics.
    Red if 2+ gates are red. Yellow if any gate is yellow. Green otherwise.
    """
    def rag(val, bm_key):
        if val is None:
            return "neutral"
        bm = BENCHMARKS.get(bm_key, {})
        if not bm:
            return "neutral"
        if val >= bm.get("realistic", 100):
            return "green"
        if val >= bm.get("conservative", 100):
            return "yellow"
        return "red"

    statuses = [
        rag(metrics.get("lemlist_open_rate"), "email_open_rate"),
        rag(metrics.get("activation_rate"),   "activation_rate"),
        rag(metrics.get("submission_rate"),   "segment_submission_rate"),
        rag(metrics.get("deals_created"),     "deals_closed_h1"),
    ]
    reds    = statuses.count("red")
    yellows = statuses.count("yellow")
    if reds >= 2:   return "red"
    if reds == 1 or yellows >= 1: return "yellow"
    return "green"


def build():
    cio     = load_source("cio")
    hubspot = load_source("hubspot")
    posthog = load_source("posthog")
    lemlist = load_source("lemlist")

    # Convenience aliases
    hs_seq        = hubspot.get("sequence_stats", {})
    cio_campaigns = cio.get("campaigns", {})

    verified_signups  = posthog.get("verified_signups",  0)
    activated_users   = posthog.get("activated_users",   0)
    cta_clicks        = posthog.get("cta_clicks_inapp",  0)
    deals_created     = hubspot.get("deals_created",     0)
    deals_closed      = hubspot.get("deals_closed_h1",   0)

    # Segment submissions: PostHog is the source of truth — product sends event there first.
    segment_submitted = posthog.get("segment_submissions", 0)

    now = datetime.now(timezone.utc).isoformat()

    metrics = {
        "meta": {
            "last_updated":  now,
            "campaign":      "Insight Hub Free Demo Access Campaign",
            "period_start":  os.environ.get("CAMPAIGN_START", "2026-03-01"),
            "period_end":    datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "is_sample_data": False,
        },
        "summary": {
            "total_verified_signups": verified_signups,
            "activation_rate":        posthog.get("activation_rate_7day", 0),
            "segment_submissions":    segment_submitted,
            "deals_in_pipeline":      deals_created,
            "overall_health":         determine_health({
                "lemlist_open_rate": lemlist.get("open_rate"),
                "activation_rate":   posthog.get("activation_rate_7day"),
                "submission_rate":   posthog.get("submission_rate_signup"),
                "deals_created":     deals_created,
            }),
        },
        "gate1": {
            "name":  "Messaging & Reach",
            "owner": "Marketing",
            "channels": {
                "lemlist": {
                    "label":        "Lemlist Email (Tier 2 Bulk)",
                    "emails_sent":  lemlist.get("sent",        0),
                    "emails_opened":lemlist.get("opened",      0),
                    "open_rate":    lemlist.get("open_rate",   0),
                    "clicks":       lemlist.get("clicked",     0),
                    "ctr":          lemlist.get("ctr",         0),
                    "replies":      lemlist.get("replied",     0),
                    "bounced":      lemlist.get("bounced",     0),
                    "unsubscribed": lemlist.get("unsubscribed",0),
                },
                "hubspot": {
                    "label":        "HubSpot Sequence (Warm Outreach)",
                    "enrolled":     hubspot.get("sequence_enrolled"),
                    "emails_sent":  hubspot.get("sequence_enrolled", 0),  # enrolled = reach proxy until weekly stats are updated
                    "emails_opened":0,
                    "open_rate":    hs_seq.get("open_rate",   0.0),
                    "clicks":       0,
                    "ctr":          hs_seq.get("click_rate", 0.0),
                    "replies":      hs_seq.get("reply_rate",  0.0),
                    "bounced":      hs_seq.get("bounce_rate", 0.0),
                    "unsubscribed": 0,
                },
                "organic": {
                    "label":               "Organic",
                    "landing_page_visits": None,
                    "source":              "UTM tracking",
                },
            },
            "landing_page": {
                "total_visits":          hubspot.get("landing_page_visits"),
                "cvr_to_signup_page":    None,
                "signup_page_visits":    None,
            },
        },
        "gate2": {
            "name":  "Sign-Up & Account Creation",
            "owner": "Marketing + Product",
            "signup_page_visits":      posthog.get("signup_page_visits", None),
            "verified_signups":        verified_signups,
            "signup_conversion_rate":  posthog.get("signup_conversion_rate", None),
            "signups_by_source": {
                "customer_io":       posthog.get("signups_by_utm_source", {}).get("customer_io") or None,
                "lemlist":           posthog.get("signups_by_utm_source", {}).get("lemlist") or None,
                "hubspot":           posthog.get("signups_by_utm_source", {}).get("hubspot") or None,
                "linkedin":          posthog.get("signups_by_utm_source", {}).get("linkedin") or None,
                "temedica_website":  posthog.get("signups_by_utm_source", {}).get("temedica_website") or None,
            },
        },
        "gate3": {
            "name":  "Onboarding & Activation",
            "owner": "Product + Marketing",
            "verified_signups":      verified_signups,
            "logged_in_within_48h":  posthog.get("logged_in_within_48h", 0),
            "login_48h_rate":        posthog.get("login_48h_rate",        0),
            "activated_users":       activated_users,
            "activation_rate_7day":  posthog.get("activation_rate_7day",  0),
            "weekly_retention": {
                "week1": posthog.get("activation_rate_7day"),
                "week2": None, "week3": None,
                "week4": None, "week5": None, "week6": None,
            },
        },
        "gate4": {
            "name":  "Market Monitor Submission",
            "owner": "Product",
            "verified_signups":               verified_signups,
            "activated_users":                activated_users,
            "segment_submissions":            segment_submitted,
            "submission_rate_from_signup":    posthog.get("submission_rate_signup",    0),
            "submission_rate_from_activation":posthog.get("submission_rate_activation",0),
            "cio_nurture":                    cio_campaigns.get("pta"),
        },
        "gate5": {
            "name":  "Commercial Conversion",
            "owner": "Commercial (Ludger, Dennis, Max)",
            "segment_submissions":       segment_submitted,
            "cta_clicks_inapp":          cta_clicks,
            "commercial_touch_rate":     posthog.get("commercial_touch_rate", 0),
            "sales_followup_within_1day":None,
            "sales_followup_rate":       None,
            "deals_created":             deals_created,
            "deals_closed_h1":           deals_closed,
            "deals_by_stage":            hubspot.get("deals_by_stage", {}),
            "h1_goal":                   5,
            "cio_nurture": {
                "core_journey":    cio_campaigns.get("core_journey"),
                "urgency_journey": cio_campaigns.get("urgency_journey"),
            },
        },
        "benchmarks": BENCHMARKS,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(metrics, f, indent=2)

    print(f"✓ metrics.json written to {OUTPUT_FILE}", file=sys.stderr)
    print(f"  Overall health: {metrics['summary']['overall_health']}", file=sys.stderr)
    print(f"  Verified sign-ups: {verified_signups}", file=sys.stderr)
    print(f"  Activation rate: {posthog.get('activation_rate_7day',0)}%", file=sys.stderr)
    print(f"  Deals created: {deals_created}", file=sys.stderr)


if __name__ == "__main__":
    build()
