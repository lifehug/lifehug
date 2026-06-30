#!/usr/bin/env python3
"""Compatibility wrapper for the canonical person entity roster.

The old implementation wrote `state/people_roster.json` with a top-level
`people` key. Person rosters now live at `state/entity_rosters/person.json`
with top-level `entities`. This script exists only so older cron jobs or
operator muscle memory keep working while they migrate to:

    python3 system/entity_roster.py --type person ...
"""

from __future__ import annotations

import sys

from entity_roster import main


if __name__ == "__main__":
    sys.argv = [sys.argv[0], "--type", "person", *sys.argv[1:]]
    raise SystemExit(main())
