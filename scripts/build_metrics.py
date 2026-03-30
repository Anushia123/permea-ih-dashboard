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
    "email_open_rate":       {"conservative": 60, "realistic": 65, "optimal": 70},
    "email_ctr":             {"conservative": 25, "realistic": 30, "optimal": 35},
    "account_creation_rate": {"conservative": 30, "realistic": 35, "optimal": 40},
    "activation_rate":       {"conservative": 60, "realistic": 65, "optimal": 75},
    "segment_submission_rate":{"conservative": 40, "realistic": 45, "optimal": 55},
    "sales_evaluation_rate": {"conservative": 55, "realistic": 60, "optimal": 70},
    "deal_close_rate":       {"conservative": 25, "realistic": 30, "optimal": 35},
    "deals_closed_h1":       {"conservative": 2,  "realistic": 4,  "optimal": 7},
    "linkedin_ctr":          {"conservative": 0.3,"realistic": 0.5,"optimal": 0.6},
    "landing_page_cvr":      {"conservative": 15, "realistic": 20, "optimal": 25},
}


def load_source(name):
    """Load JSON output from a fetch script's temp file."""
    path = TEMP_DIR / f"{name}.json"
    if not path.exists():
        print(f"  ! {name}.json not found — using empty data", file=sys.stderr)
        return {}
    with open(path) as f:
        return json.load(f)


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
    hs_email   = hubspot.get("email", {})
    li_data    = load_source("linkedin")  # optional — may not exist yet

    verified_signups  = posthog.get("verified_signups",  0)
    activated_users   = posthog.get("activated_users",   0)
    cta_clicks        = posthog.get("cta_clicks_inapp",  0)
    deals_created     = hubspot.get("deals_created",     0)
    deals_closed      = hubspot.get("deals_closed_h1",   0)

    # Segment submissions: CIO is primary source (product sends event directly to CIO journey).
    # Falls back to PostHog if CIO returned None (API error or event not yet tracked in CIO).
    cio_segment = cio.get("segment_submissions")
    if cio_segment is not None:
        segment_submitted = cio_segment
        print("  ✓ build: using CIO segment_submissions count", file=sys.stderr)
    else:
        segment_submitted = posthog.get("segment_submissions", 0)
        print("  ! build: CIO segment_submissions unavailable — using PostHog fallback", file=sys.stderr)

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
                    "label":        "HubSpot Email (Tier 1 Personal)",
                    "emails_sent":  hs_email.get("sent",       0),
                    "emails_opened":hs_email.get("opened",     0),
                    "open_rate":    hs_email.get("open_rate",  0),
                    "clicks":       hs_email.get("clicked",    0),
                    "ctr":          hs_email.get("ctr",        0),
                    "replies":      0,
                    "bounced":      0,
                    "unsubscribed": 0,
                },
                "linkedin": {
                    "label":       "LinkedIn Paid",
                    "impressions": li_data.get("impressions", None),
                    "clicks":      li_data.get("clicks",      None),
                    "ctr":         li_data.get("ctr",         None),
                    "cost_per_click": li_data.get("cost_per_click", None),
                    "conversions": li_data.get("conversions", None),
                    "spend":       li_data.get("spend",       None),
                    "status":      "live" if li_data else "pending_oauth",
                },
                "google": {
                    "label":  "Google Paid",
                    "status": "deferred",
                },
                "organic": {
                    "label":               "Organic",
                    "landing_page_visits": None,
                    "source":              "UTM tracking",
                },
            },
            "landing_page": {
                "total_visits":          None,
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
                "lemlist_email":  None,
                "hubspot_email":  None,
                "linkedin_paid":  None,
                "organic":        None,
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
