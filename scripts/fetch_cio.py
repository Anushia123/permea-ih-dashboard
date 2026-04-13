"""
Fetch Customer.io campaign email metrics for the Insight Hub dashboard.

NOTE: The CIO App API does not expose journey campaign metrics — all endpoints
return zeros for triggered/journey campaigns. Confirmed from CIO docs: there is
no pull analytics API for journeys (only outbound Reporting Webhooks).

Metrics are read from data/manual_overrides.json instead.
Update weekly: CIO UI > Campaigns > select campaign > Overview tab > screenshot > update file.

Output keys:
  campaigns.pta             — PTA journey (Gate 4)
  campaigns.core_journey    — Core Journey (Gate 5)
  campaigns.urgency_journey — Urgency Journey (Gate 5)
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

MANUAL_OVERRIDES_PATH = Path(__file__).parent.parent / "data" / "manual_overrides.json"


def load_manual_overrides():
    if MANUAL_OVERRIDES_PATH.exists():
        return json.loads(MANUAL_OVERRIDES_PATH.read_text())
    print("  ! manual_overrides.json not found", file=sys.stderr)
    return {}


def main():
    print("→ Loading Customer.io metrics from manual overrides…", file=sys.stderr)

    overrides = load_manual_overrides()
    journeys  = overrides.get("cio_journeys", {})

    def get_journey(key):
        j = journeys.get(key, {})
        if not j:
            return None
        return {
            "sent":       j.get("sent",      0),
            "opened":     j.get("opened",    0),
            "clicked":    j.get("clicked",   0),
            "open_rate":  j.get("open_rate", 0.0),
            "ctr":        j.get("ctr",       0.0),
            "last_updated": j.get("last_updated"),
        }

    pta      = get_journey("pta")
    core     = get_journey("core_journey")
    urgency  = get_journey("urgency_journey")

    print(f"  ✓ PTA:          sent={pta['sent'] if pta else 0}, open={pta['open_rate'] if pta else 0}%, ctr={pta['ctr'] if pta else 0}%", file=sys.stderr)
    print(f"  ✓ Core Journey: sent={core['sent'] if core else 0}", file=sys.stderr)
    print(f"  ✓ Urgency:      sent={urgency['sent'] if urgency else 0}", file=sys.stderr)

    result = {
        "source":     "customer.io",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "campaigns": {
            "pta":             pta,
            "core_journey":    core,
            "urgency_journey": urgency,
        },
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
