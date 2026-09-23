"""Import the frontend's calendar JSON into `activities`, once.

    python -m scripts.import_events [--force] [--anchor]

Phase 5 moves the public calendar out of
`public-frontend/src/content/data/events.json` and into the CMS, alongside the
attendance sessions admins already manage. One table, two audiences: the member
app reads the attendance fields, the public site reads the ones added in 0007.

Two deliberate choices:

* Imported rows are `is_attendance_event=False`. The prototype's "weekly
  session" entries describe sessions for readers; the real attendance rows are
  created by the admin dashboard and carry the check-in code. Importing these
  as attendance events would collide with the one-session-per-date rule and
  put a second Monday on the members' calendar.
* `is_public=True`, because that is what this data is — it was on the public
  site already. Everything else in the table stays private, as 0007 defaults.

`--anchor` shifts every date so the second event lands three days from today,
reproducing the prototype's `DEMO_DATES` behaviour. Useful for a dev database
that should look alive; never use it against production.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, ".")

from app.db import SessionLocal  # noqa: E402
from app.models import Activity  # noqa: E402

# See import_courses.py: the seed data lives in this repo so the import works
# on the server, where no frontend checkout exists.
SOURCE = Path(__file__).resolve().parent / "seed_data" / "events.json"

ANCHOR_INDEX = 1
ANCHOR_OFFSET_DAYS = 3


def shift_days(events: list[dict]) -> int:
    """How far to move every date so the anchor event is a few days away."""
    if not events:
        return 0
    anchor = events[min(ANCHOR_INDEX, len(events) - 1)]
    target = date.today() + timedelta(days=ANCHOR_OFFSET_DAYS)
    return (target - date.fromisoformat(anchor["date"])).days


def main() -> int:
    force = "--force" in sys.argv
    anchor = "--anchor" in sys.argv
    if not SOURCE.exists():
        print(f"events JSON not found: {SOURCE}")
        return 1

    events = sorted(
        json.loads(SOURCE.read_text(encoding="utf-8")), key=lambda e: e["date"]
    )
    offset = shift_days(events) if anchor else 0
    db = SessionLocal()

    imported = 0
    for data in events:
        slug = data["slug"]
        existing = db.query(Activity).filter(Activity.public_slug == slug).first()
        if existing is not None and not force:
            print(f"skip {slug} (already imported)")
            continue
        if existing is not None:
            db.delete(existing)
            db.flush()

        when = date.fromisoformat(data["date"]) + timedelta(days=offset)
        price = data.get("price") or {}
        db.add(
            Activity(
                title=data["title"]["id"],
                title_en=data["title"].get("en", ""),
                description=None,
                date=when.isoformat(),
                start_time=data.get("startTime", "19:00"),
                end_time=data.get("endTime", "21:00"),
                # See the module docstring: public-calendar content, not a
                # check-in session.
                is_attendance_event=False,
                is_holiday=data.get("isHoliday", False),
                is_public=True,
                public_slug=slug,
                summary_id=data["summary"]["id"],
                summary_en=data["summary"].get("en", ""),
                public_description=data.get("description", []),
                images=data.get("images", []),
                links=data.get("links", []),
                kind=data.get("kind", "weekly"),
                price_amount=price.get("amount"),
                venue_id=None,
            )
        )
        imported += 1
        print(f"imported {slug} ({when.isoformat()})")

    db.commit()
    db.close()
    print(f"\ndone - {imported} activities on the public calendar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
